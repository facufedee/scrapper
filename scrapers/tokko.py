"""Generic scraper for agency sites built on Tokko Broker
(static.tokkobroker.com), a very widely used Argentine/LatAm real estate
SaaS — found via Taburet (Ituzaingó). Given how common Tokko is, this is
worth having as a reusable adapter the same way ArgenCasas/Houzez are.

Discovery: `/Propiedades` is a search page whose results are rendered
server-side but only when the full querystring of filter params is present
(a bare `/Propiedades` with no params renders the empty search form instead)
— `?p=N` pages through results, 20 per page.

Each detail page (`/p/{id}-{slug}`) is plain server-rendered HTML: price and
operation in `.operation-type-div`/`.operation-val`, a generic
`.ficha_detalle_item` list (`<b>Label</b><br/>Value`) for m²/rooms/etc, and
a description in `#prop-desc` whose HTML content is itself entity-encoded
(literal `&lt;p&gt;` in the text) so it needs an extra unescape + tag-strip
pass. Photos are `img.slider-thumb[data-big]`. Lat/lon isn't always present
(not every listing has geocoding filled in on Tokko), so it's best-effort.
"""

import html as html_module
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

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}

_FIELD_PATTERNS = [
    (re.compile(r"terreno"), "land_m2"),
    (re.compile(r"cubiert"), "covered_m2"),
    (re.compile(r"total construido|superficie total|total\b"), "total_m2"),
    (re.compile(r"dormitorio"), "bedrooms"),
    (re.compile(r"ambiente"), "total_rooms"),
    (re.compile(r"^ba[ñn]o"), "bathrooms"),
    (re.compile(r"ubicaci[oó]n"), "neighborhood"),
]

_SEARCH_QS = "q=&currency=ANY&operation=&locations=&location_type=&ptypes=&o=2,2"


class TokkoScraper(BaseScraper):
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
        page = 1
        seen = set()
        count = 0
        while True:
            html = self._get(f"{self.base_url}/Propiedades?{_SEARCH_QS}&p={page}")
            if not html:
                break
            paths = re.findall(r'href="(/p/\d+-[^"]+)"', html)
            new_paths = [p for p in dict.fromkeys(paths) if p not in seen]
            if not new_paths:
                break
            for path in new_paths:
                seen.add(path)
                yield f"{self.base_url}{path}"
                count += 1
                if max_items is not None and count >= max_items:
                    return
            page += 1
            time.sleep(self.delay)

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
        id_match = re.search(r"/p/(\d+)-", url)
        source_id = id_match.group(1) if id_match else None
        if not source_id:
            return None

        soup = BeautifulSoup(html, "lxml")

        og_title = soup.select_one('meta[property="og:title"]')
        title = og_title.get("content") if og_title else None

        addr_el = soup.select_one(".title-address")
        address = addr_el.get_text(strip=True) if addr_el else None

        # Tokko Broker has (at least) two theme families across tenants —
        # this one (.operation-type-div/.operation-val, found via Taburet)
        # and a newer one (.prop-detail-op-tag/.prop-detail-price-list,
        # found via Colonna) with otherwise-unrelated markup. Fields not
        # covered by either fallback (address, m²/rooms) stay best-effort
        # None on the newer theme rather than guessing at more selectors.
        op_el = soup.select_one(".operation-type-div") or soup.select_one(".prop-detail-op-tag")
        operation_raw = op_el.get_text(strip=True).lower() if op_el else ""
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        price_el = soup.select_one(".operation-val span") or soup.select_one(".prop-detail-price-list .price-number")
        currency, price = _parse_price(price_el.get_text(strip=True) if price_el else "")

        fields = {}
        for item in soup.select(".ficha_detalle_item"):
            b_tag = item.find("b")
            if not b_tag:
                continue
            label = b_tag.get_text(strip=True).lower()
            value = item.get_text(" ", strip=True).replace(b_tag.get_text(strip=True), "", 1).strip()
            fields[label] = value

        mapped = {}
        for label, value in fields.items():
            dest = next((d for pattern, d in _FIELD_PATTERNS if pattern.search(label)), None)
            if not dest or dest in mapped:
                continue
            if dest in ("land_m2", "covered_m2", "total_m2"):
                mapped[dest] = _to_float(value)
            elif dest in ("bedrooms", "bathrooms", "total_rooms"):
                mapped[dest] = _first_int(value)
            else:
                mapped[dest] = value

        desc_el = soup.select_one("#prop-desc") or soup.select_one(".full-description")
        description = None
        if desc_el:
            unescaped = html_module.unescape(desc_el.get_text())
            description = re.sub(r"<[^>]+>", "\n", unescaped)
            description = re.sub(r"\n{2,}", "\n\n", description).strip()
        if not description:
            og_desc = soup.select_one('meta[property="og:description"]')
            description = og_desc.get("content", "").strip() if og_desc else None

        photos = [img.get("data-big") for img in soup.select("img.slider-thumb") if img.get("data-big")]
        if not photos:
            photos = list(dict.fromkeys(a.get("href") for a in soup.select("a.pswp-elem") if a.get("href")))

        map_match = re.search(r'"lat"\s*:\s*"?(-?[\d.]+)"?,\s*"lng"\s*:\s*"?(-?[\d.]+)"?', html)
        lat = _plain_float(map_match.group(1)) if map_match else None
        lon = _plain_float(map_match.group(2)) if map_match else None

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
            address=address,
            neighborhood=mapped.get("neighborhood"),
            lat=lat,
            lon=lon,
            total_rooms=mapped.get("total_rooms"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            land_m2=mapped.get("land_m2"),
            covered_m2=mapped.get("covered_m2"),
            total_m2=mapped.get("total_m2"),
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw=fields,
        )


def _parse_price(text: str):
    text = (text or "").strip()
    m = re.match(r"(USD|ARS|\$)\s*([\d.,]+)", text)
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
