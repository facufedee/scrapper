"""ZonaProp (Argentina) scraper.

Unlike Remax, ZonaProp is behind Cloudflare bot protection (JS challenge) and
its robots.txt explicitly disallows its internal APIs (/avisos-api/, /leads-api/)
and deep search-result pagination (only pages 1-5 of any filtered search are
allowed). So this adapter takes a different, robots.txt-compliant route:

1. Discovery: ZonaProp publishes sitemap files (allowed for crawlers by
   convention) listing every individual classified/listing URL directly —
   no need to page through search results at all.
2. Extraction: each listing detail page is server-rendered behind Cloudflare,
   so a plain HTTP request gets the interstitial challenge page instead of
   data. A real (headless) browser passes the challenge fine, so this adapter
   drives one via Playwright and reads the data straight out of the page:
   the Google Tag Manager `dataLayer` push (structured tracking fields),
   a schema.org JSON-LD block, and a couple of stable DOM anchors
   (#section-icon-features-property, .price-value, images under /avisos/).

Because discovery is sitemap-based rather than paginated search results, the
`operation` argument here is applied as a post-fetch filter (each listing's
real operation is only known once its detail page is read), and `max_pages`
is reused as "max number of listing detail pages to visit" — a throttle knob
for testing, not a literal page count.
"""

import gzip
import logging
import re
import time
from typing import Iterator, Optional

from playwright.sync_api import sync_playwright

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zonaprop.com.ar"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemaps_https.xml"

OPERATION_MAP = {
    "venta": "sale",
    "alquiler": "rent",
    "alquiler temporal": "temporal",
    "alquiler temporario": "temporal",
}


class ZonaPropScraper(BaseScraper):
    source_name = "zonaprop"
    all_in_one = True

    # Cloudflare here escalates to blocking outright if it sees too many
    # requests too fast from one IP (confirmed empirically), so this default
    # is deliberately much more conservative than Remax's — a handful of
    # requests per minute, not per second.
    DEFAULT_DELAY = 6.0

    def __init__(self, delay: Optional[float] = None, headless: bool = True):
        self.delay = delay if delay is not None else self.DEFAULT_DELAY
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    # -- browser lifecycle -------------------------------------------------

    def _ensure_browser(self):
        if self._context is not None:
            return
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(user_agent=config.USER_AGENT)
        # one real navigation to pick up the Cloudflare clearance cookie,
        # reused by every following page/request in this context
        page = self._context.new_page()
        page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
        page.close()

    def close(self):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._context = self._browser = self._playwright = None

    # -- discovery -----------------------------------------------------------

    def _fetch_text(self, url: str, retries: int = 3) -> str:
        is_gzip = url.endswith(".gz")
        for attempt in range(1, retries + 1):
            resp = self._context.request.get(url, timeout=30000)
            resp_content = resp.body()
            # .gz files start with the gzip magic bytes regardless of the
            # (often mislabeled) content-type header; a Cloudflare challenge
            # page won't, so that's the reliable signal to check.
            looks_valid = resp_content[:2] == b"\x1f\x8b" if is_gzip else b"<html" not in resp_content[:200].lower()
            if not looks_valid:
                logger.warning(
                    "Cloudflare challenge fetching %s (attempt %s/%s), refreshing clearance",
                    url, attempt, retries,
                )
                time.sleep(3 * attempt)
                page = self._context.new_page()
                page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
                page.close()
                continue
            if is_gzip:
                resp_content = gzip.decompress(resp_content)
            return resp_content.decode("utf-8")
        raise RuntimeError(f"Got HTML (likely a Cloudflare challenge) fetching {url} after {retries} attempts")

    def iter_sitemap_urls(self, max_items: Optional[int] = None) -> Iterator[str]:
        self._ensure_browser()
        index_xml = self._fetch_text(SITEMAP_INDEX_URL)
        sitemap_files = [
            loc for loc in re.findall(r"<loc>(.*?)</loc>", index_xml) if "sitemap_prop_" in loc
        ]
        logger.info("zonaprop found %s property sitemap files", len(sitemap_files))

        seen = set()
        count = 0
        for sitemap_url in sitemap_files:
            xml = self._fetch_text(sitemap_url)
            for url in re.findall(r"<loc>(.*?)</loc>", xml):
                if url in seen:
                    continue
                seen.add(url)
                yield url
                count += 1
                if max_items is not None and count >= max_items:
                    return

    # -- listing scraping -----------------------------------------------------

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        self._ensure_browser()
        page = self._context.new_page()
        try:
            for url in self.iter_sitemap_urls(max_items=max_pages):
                item = self._scrape_detail(page, url)
                if item is None:
                    continue
                if operation != "all" and item.operation != operation:
                    continue
                yield item
                time.sleep(self.delay)
        finally:
            page.close()

    def _scrape_detail(self, page, url: str, retries: int = 4) -> Optional[PropertyItem]:
        try:
            for attempt in range(1, retries + 1):
                resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
                if resp is None or resp.status == 404:
                    return None
                if "Just a moment" not in page.title():
                    break
                logger.warning(
                    "Cloudflare challenge on %s (attempt %s/%s), backing off", url, attempt, retries
                )
                time.sleep(4 * attempt)
            else:
                logger.error("Gave up on %s after %s Cloudflare challenges", url, retries)
                return None

            data = page.evaluate(_EXTRACT_JS)
            return self._normalize(url, data)
        except Exception:
            logger.exception("Failed to scrape ZonaProp listing %s", url)
            return None

    def _normalize(self, url: str, data: dict) -> Optional[PropertyItem]:
        dl = data.get("trackEvent") or {}
        ld = data.get("jsonLd") or {}

        source_id = dl.get("idAviso") or _id_from_url(url)
        if not source_id:
            return None

        raw_operation = (dl.get("tipoDeOperacion") or "").strip().lower()
        operation = OPERATION_MAP.get(raw_operation, raw_operation or "sale")

        price_str = (dl.get("precioVenta") or "").strip() or (dl.get("precioAlquiler") or "").strip()
        currency, price = _parse_price(price_str)

        features = data.get("features") or []
        total_m2 = covered_m2 = total_rooms = bedrooms = bathrooms = None
        for feat in features:
            if (m := re.search(r"([\d.,]+)\s*m²\s*tot", feat)):
                total_m2 = _to_float(m.group(1))
            elif (m := re.search(r"([\d.,]+)\s*m²\s*cub", feat)):
                covered_m2 = _to_float(m.group(1))
            elif (m := re.search(r"(\d+)\s*amb", feat)):
                total_rooms = int(m.group(1))
            elif (m := re.search(r"(\d+)\s*dorm", feat)):
                bedrooms = int(m.group(1))
            elif (m := re.search(r"(\d+)\s*ba[ñn]o", feat)):
                bathrooms = int(m.group(1))

        address_obj = ld.get("address") or {}

        return PropertyItem(
            source=self.source_name,
            source_id=str(source_id),
            url=url,
            title=ld.get("name") or data.get("title"),
            description=data.get("description") or ld.get("description"),
            property_type=dl.get("tipoDePropiedad"),
            operation=operation,
            status=None,
            price=price,
            currency=currency,
            expenses_price=None,
            expenses_currency=None,
            address=address_obj.get("streetAddress") or data.get("addressLine"),
            neighborhood=dl.get("barrio") or address_obj.get("addressRegion"),
            city=dl.get("ciudad"),
            province=dl.get("provincia"),
            lat=None,
            lon=None,
            total_rooms=total_rooms,
            bedrooms=bedrooms,
            bathrooms=bathrooms or dl.get("bathrooms"),
            land_m2=None,
            covered_m2=covered_m2,
            total_m2=total_m2,
            agent_name=dl.get("listed_by"),
            agent_phone=None,
            agent_email=None,
            office_name=dl.get("listed_by"),
            photos=data.get("photos") or [],
            raw=data,
        )


_EXTRACT_JS = """
() => {
  const dl = Array.isArray(window.dataLayer) ? window.dataLayer : [];
  const trackEvent = dl.find(e => e && e.event === 'track_content_group') || {};

  const ldScripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
  let jsonLd = {};
  for (const s of ldScripts) {
    try {
      const parsed = JSON.parse(s.textContent);
      if (['Apartment', 'House', 'Place', 'Product'].includes(parsed['@type'])) { jsonLd = parsed; break; }
    } catch (e) {}
  }

  const descEl = document.querySelector('[id*="description" i]');
  const description = descEl ? descEl.textContent.trim() : null;

  const featureLis = Array.from(document.querySelectorAll('#section-icon-features-property li, ul.section-icon-features li'));
  const features = featureLis.map(li => li.textContent.replace(/\\s+/g, ' ').trim());

  const addressEl = document.querySelector('article') || document.body;
  const addrMatch = (addressEl.textContent || '').match(/([^\\n]+,\\s*[^\\n]+,\\s*[^\\n]+)/);

  const photos = [...new Set(Array.from(document.querySelectorAll('img'))
    .map(i => i.src)
    .filter(src => /\\/avisos\\//.test(src)))];

  return {
    trackEvent,
    jsonLd,
    description,
    features,
    photos,
    title: document.title,
  };
}
"""


def _id_from_url(url: str) -> Optional[str]:
    m = re.search(r"-(\d+)\.html", url)
    return m.group(1) if m else None


def _parse_price(price_str: str):
    price_str = (price_str or "").strip()
    if not price_str:
        return None, None
    m = re.match(r"([A-Za-z$]+)\s*([\d.,]+)", price_str)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if "usd" in currency_raw.lower() or "$" in currency_raw and "u" in currency_raw.lower() else (
        "ARS" if "ars" in currency_raw.lower() or currency_raw == "$" else currency_raw.upper()
    )
    return currency, _to_float(number_raw)


def _to_float(value: str) -> Optional[float]:
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".") if "," in value else value.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
