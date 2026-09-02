"""Generic scraper for agency sites built on a shared small-agency website
platform recognizable by `/ad/{slug}` detail URLs and a consistent Bootstrap
template (`.property-price`, `.icon_default`, `.btn-group button` stat
widgets, `.pro_det` description). Found via Inmobiliaria Spinelli (Haedo)
and confirmed identical on Gabriel Basta (Merlo).

Neither site found so far has a dedicated search/listing page or sitemap —
`/propiedades` 404s and nothing in nav links to one — so discovery is
limited to whatever `/ad/` links appear on the homepage ("destacadas"/
featured properties). That's a real limitation of this platform tier, not a
scraper bug: it means coverage here is partial, not the full catalog.
"""

import logging
import re
import time
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

_OPERATION_MAP = {"en venta": "sale", "en alquiler": "rent", "en alquiler temporal": "temporal"}


class AdPropScraper(BaseScraper):
    all_in_one = True

    def __init__(self, base_url: str, source_name: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get(self, url: str) -> Optional[str]:
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_urls(self, max_items: Optional[int] = None) -> Iterator[str]:
        html = self._get(f"{self.base_url}/")
        if not html:
            return
        pattern = re.escape(self.base_url) + r"/ad/[a-z0-9-]+"
        urls = sorted(set(re.findall(rf'href="({pattern})"', html)))
        for i, url in enumerate(urls):
            if max_items is not None and i >= max_items:
                return
            yield url

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        for url in self.iter_urls(max_items=max_pages):
            item = self._scrape_detail(url)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, url: str) -> Optional[PropertyItem]:
        html = self._get(url)
        if html is None:
            return None
        try:
            return self._normalize(url, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, url)
            return None

    def _normalize(self, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        code_match = re.search(r"C[oó]digo:\s*(\d+)", soup.get_text())
        source_id = code_match.group(1) if code_match else None
        if not source_id:
            return None

        title_el = soup.select_one("h5.color-secondery") or soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else None

        status_el = soup.select_one(".sale")
        operation_raw = status_el.get_text(strip=True).lower() if status_el else ""
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        addr_el = soup.select_one(".icon_default p")
        address_full = addr_el.get_text(" ", strip=True) if addr_el else None

        price_el = soup.select_one(".property-price")
        currency, price = _parse_price(price_el.get_text(" ", strip=True) if price_el else "")

        stats = {}
        for btn in soup.select(".btn-group button"):
            label_parts = [t for t in btn.stripped_strings]
            if len(label_parts) >= 2:
                *label_words, value = label_parts
                stats[" ".join(label_words).lower()] = value

        desc_el = soup.select_one(".pro_det p")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        map_match = re.search(r"maps/embed/v1/place\?key=[^&]*&q=(-?[\d.]+),\s*(-?[\d.]+)", html)
        lat = _plain_float(map_match.group(1)) if map_match else None
        lon = _plain_float(map_match.group(2)) if map_match else None

        photo_pattern = re.escape(self.base_url) + r"/uploads/[^\"]+\.jpe?g"
        photos = sorted(set(re.findall(rf'src="({photo_pattern})"', html)))

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            description=description,
            property_type=None,
            operation=operation,
            price=price,
            currency=currency,
            address=address_full,
            lat=lat,
            lon=lon,
            bedrooms=_first_int(stats.get("dormitorios")),
            total_rooms=_first_int(stats.get("ambientes")),
            bathrooms=_sane_count(_first_int(stats.get("baños") or stats.get("banos"))),
            total_m2=_to_float(stats.get("m² totales") or stats.get("m2 totales")),
            covered_m2=_to_float(stats.get("m² cubiertos") or stats.get("m2 cubiertos")),
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw=stats,
        )


def _parse_price(text: str):
    text = (text or "").strip()
    m = re.search(r"(USD|ARS|\$)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency = "USD" if m.group(1) == "USD" else "ARS"
    return currency, _to_float(m.group(2))


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    m = re.match(r"(-?[\d.,]+)", value)
    if not m:
        return None
    number = m.group(1)
    if "," in number:
        cleaned = number.replace(".", "").replace(",", ".")
    else:
        parts = number.split(".")
        cleaned = number.replace(".", "") if len(parts) > 1 and len(parts[-1]) == 3 else number
    try:
        return float(cleaned)
    except ValueError:
        return None


def _plain_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _sane_count(value: Optional[int]) -> Optional[int]:
    # this platform's "Baños" widget occasionally renders two concatenated
    # numbers (seen as e.g. 2510 on one Spinelli listing) — a template
    # glitch on their end, not something worth propagating as a room count
    if value is None or value > 20:
        return None
    return value
