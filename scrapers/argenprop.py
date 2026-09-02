"""Argenprop (Argentina) scraper.

Unlike ZonaProp, Argenprop's pages are plain server-rendered HTML — no SPA,
no client-side data fetch, everything (price, features, description, agent,
lat/lon) is already in the initial response. That means a plain `requests`
call is enough, no headless browser needed... most of the time.

The catch: Argenprop sits behind AWS WAF Bot Control, and detail pages
("fichas") can escalate to an interactive CAPTCHA ("Human Verification")
under enough automated-looking traffic from one IP. That's a harder wall than
Cloudflare's computational challenge (which a plain browser can solve by
itself) — a CAPTCHA needs an actual human, so there is no "retry harder"
here. This adapter goes very conservatively (long delay between requests,
realistic headers) and, if it ever sees the challenge page, stops immediately
instead of hammering a wall that won't move.

Discovery is sitemap-based, same idea as ZonaProp: robots.txt publishes
per-region "ficha" (listing detail) sitemaps, which are themselves sitemap
indexes pointing to the actual numbered shard files with the listing URLs.
"""

import gzip
import logging
import re
import time
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

BASE_URL = "https://www.argenprop.com"

# "ficha" sitemaps only (individual listings) covering Argentina; skips
# sitemap-listing-* (search result pages, not needed), sitemap-inmobiliarias /
# sitemap-emprendimiento / sitemap-country (different content types), and the
# uruguay / otros-exterior regions (out of scope for this project).
FICHA_SITEMAPS = [
    f"{BASE_URL}/sitemaps/sitemap-ficha-capital-federal.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-gba-norte.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-gba-sur.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-gba-oeste.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-resto-baires.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-costa-atlantica.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-cordoba.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-cuyo.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-santa-fe.xml.gz",
    f"{BASE_URL}/sitemaps/sitemap-ficha-otros-argentina.xml.gz",
]

OPERATION_MAP = {
    "venta": "sale",
    "alquiler": "rent",
    "alquiler temporal": "temporal",
    "alquiler temporario": "temporal",
}

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/",
}


class WafBlockedError(RuntimeError):
    """Raised when Argenprop's AWS WAF shows its CAPTCHA challenge instead of
    real content. There's no automatic way past this (it needs a human), so
    callers should stop rather than retry."""


class ArgenpropScraper(BaseScraper):
    source_name = "argenprop"
    all_in_one = True
    # Deliberately conservative: the WAF here escalates to a CAPTCHA (not just
    # a solvable JS challenge) under volume, and a CAPTCHA can't be waited out
    # the way Cloudflare's challenge sometimes can.
    DEFAULT_DELAY = 5.0

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else self.DEFAULT_DELAY
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT, **_HEADERS})

    def close(self) -> None:
        self.session.close()

    # -- discovery -----------------------------------------------------------

    def _fetch_gz(self, url: str) -> str:
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return gzip.decompress(resp.content).decode("utf-8")

    def iter_sitemap_urls(self, max_items: Optional[int] = None) -> Iterator[str]:
        count = 0
        for top_level in FICHA_SITEMAPS:
            xml = self._fetch_gz(top_level)
            locs = re.findall(r"<loc>(.*?)</loc>", xml)
            # a top-level "ficha" sitemap is itself an index of shard files
            # when its entries end in .xml.gz; otherwise it's already the
            # urlset with real listing URLs (small regions may not be sharded)
            shard_urls = [loc for loc in locs if loc.endswith(".xml.gz")]

            if shard_urls:
                for shard_url in shard_urls:
                    shard_xml = self._fetch_gz(shard_url)
                    for url in re.findall(r"<loc>(.*?)</loc>", shard_xml):
                        yield url
                        count += 1
                        if max_items is not None and count >= max_items:
                            return
            else:
                for url in locs:
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
        for url in self.iter_sitemap_urls(max_items=max_pages):
            item = self._scrape_detail(url)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, url: str) -> Optional[PropertyItem]:
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        if resp.status_code == 202 or "Human Verification" in resp.text or "awsWafCookieDomainList" in resp.text:
            raise WafBlockedError(
                f"Argenprop mostró el challenge de AWS WAF en {url}. "
                "Esto necesita resolución humana, no tiene sentido reintentar solo — frenando."
            )
        resp.raise_for_status()
        try:
            return self._normalize(url, resp.text)
        except Exception:
            logger.exception("Failed to parse Argenprop listing %s", url)
            return None

    def _normalize(self, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        id_match = re.search(r"--(\d+)$", url)
        source_id = id_match.group(1) if id_match else None
        if not source_id:
            return None

        targeting = {
            k: v
            for k, v in re.findall(r"setTargeting\('([a-z_]+)',\s*'([^']*)'\)", html)
        }

        main_features = _parse_main_features(soup)
        features = _parse_labeled_features(soup)

        raw_operation = (targeting.get("tipo_operacion") or features.get("Tipo de operación") or "").strip().lower()
        operation = OPERATION_MAP.get(raw_operation, raw_operation or "sale")

        price_el = soup.select_one(".titlebar__price")
        currency, price = _parse_price(price_el.get_text(strip=True) if price_el else "")
        expenses_el = soup.select_one(".titlebar__expenses")
        expenses_currency, expenses_price = _parse_price(expenses_el.get_text(strip=True) if expenses_el else "")

        address_el = soup.select_one(".titlebar__address")
        desc_el = soup.select_one(".section-description--content")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        map_el = soup.select_one("[data-location-map]")
        lat = lon = None
        if map_el:
            # these come as "-34,57948" (Argentine decimal comma) — _to_float
            # already treats a comma as the decimal separator, don't pre-convert it
            lat = _to_float(map_el.get("data-latitude"))
            lon = _to_float(map_el.get("data-longitude"))

        agent_el = soup.select_one("[data-agent-more-properties]")

        total_m2 = _to_float(_strip_m2(features.get("Sup. Total")))
        covered_m2 = _to_float(_strip_m2(features.get("Sup. Cubierta")))
        bathrooms = _first_int(main_features.get("Baños") or features.get("Baños"))
        bedrooms = _first_int(main_features.get("Dormitorios") or features.get("Dormitorios"))
        total_rooms = _rooms_to_int(main_features.get("Ambientes"))

        photos = _extract_photos(html)

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=_meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else None),
            description=description,
            property_type=main_features.get("_property_type") or targeting.get("tipo_inmueble"),
            operation=operation,
            status=None,
            price=price,
            currency=currency,
            expenses_price=expenses_price,
            expenses_currency=expenses_currency,
            address=address_el.get_text(strip=True) if address_el else None,
            neighborhood=targeting.get("barrio_nombre") or targeting.get("localidad_nombre"),
            city=targeting.get("localidad_nombre") or targeting.get("partido_nombre"),
            province=targeting.get("provincia_nombre"),
            lat=lat,
            lon=lon,
            total_rooms=total_rooms,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            land_m2=None,
            covered_m2=covered_m2,
            total_m2=total_m2,
            agent_name=agent_el.get_text(strip=True) if agent_el else None,
            agent_phone=None,
            agent_email=None,
            office_name=agent_el.get_text(strip=True) if agent_el else None,
            photos=photos,
            raw={"features": features, "main_features": main_features, "targeting": targeting},
        )


def _meta(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=prop)
    return tag.get("content") if tag else None


def _parse_main_features(soup: BeautifulSoup) -> dict:
    out = {}
    lis = soup.select("ul.property-main-features li")
    for i, li in enumerate(lis):
        p = li.find("p")
        value = p.get_text(strip=True) if p else None
        title = li.get("title")
        if title:
            out[title] = value
        elif i == 0:
            out["_property_type"] = value
    return out


def _parse_labeled_features(soup: BeautifulSoup) -> dict:
    out = {}
    for li in soup.select("ul.property-features li"):
        h3 = li.find("h3")
        if not h3:
            continue
        strong = h3.find("strong")
        if not strong:
            continue
        value = strong.get_text(strip=True)
        label = h3.get_text(" ", strip=True).replace(value, "").strip().rstrip(":").strip()
        if label:
            out[label] = value
        else:
            out.setdefault("_flags", []).append(value)
    return out


def _extract_photos(html: str) -> list:
    preload = re.search(r'static-content/([\w-]+)/[a-f0-9-]+_u_medium\.jpg', html)
    if not preload:
        return []
    album_id = preload.group(1)
    urls = re.findall(rf'(https://www\.argenprop\.com/static-content/{re.escape(album_id)}/[a-f0-9-]+_u_medium\.jpg)', html)
    seen = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen


def _parse_price(text: str):
    text = (text or "").strip().replace("&plus;", "+").replace("&amp;plus;", "+")
    if not text:
        return None, None
    m = re.match(r"[+\s]*([A-Za-z$]+)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if "usd" in currency_raw.lower() else ("ARS" if "$" in currency_raw else currency_raw.upper())
    return currency, _to_float(number_raw)


def _strip_m2(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return re.sub(r"\s*m2\s*$", "", text.strip())


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _rooms_to_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    if "mono" in text.lower():
        return 1
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".") if "," in value else value.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
