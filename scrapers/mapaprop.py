"""Generic adapter for the Mapaprop platform (`Mapaprop.com`), confirmed on
MSV Inmobiliaria and Portela Propiedades.

Server-rendered jQuery-era site. Detail pages have a decoy `<h1>Buscador de
propiedades</h1>` outside the actual property block — the real content
(title, price, description, details table, photos) lives inside
`div.page.page-property`, so every selector below is scoped under that.

Listing (`/buscar/?type=&operation=&page=N`) mixes venta+alquiler by default.
Pagination is *not* a clean offset — consecutive pages overlap heavily (only
a handful of genuinely new items per page step) and clamp to a repeating set
once past the end, so discovery just keeps a global `seen` set and stops
once a page contributes zero new items (same approach as scrapers/carlucci.py).

Operation (sale/rent) isn't in the detail page markup in an obviously
structured way, but the URL slug always starts with "venta-de-" or
"alquiler-de-", so it's parsed from the path instead.

No robots.txt on either confirmed site (both 404), so no discovery
restrictions apply.
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

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

_DETAIL_LINK_RE = re.compile(r"/propiedad/[a-z0-9-]+-\d+-\d+")

_DETAIL_FIELD_PATTERNS = [
    (re.compile(r"superficie cubierta"), "covered_m2"),
    (re.compile(r"superficie total|superficie de lote|superficie del terreno"), "total_m2"),
    (re.compile(r"^dormitorio"), "bedrooms"),
    (re.compile(r"^ambiente"), "total_rooms"),
    (re.compile(r"ba[ñn]os?\b"), "bathrooms"),
]

_OPERATION_RE = re.compile(r"/propiedad/(venta|alquiler)-de-")


class MapapropScraper(BaseScraper):
    all_in_one = True  # /buscar mixes venta+alquiler in one paginated list

    def __init__(self, base_url: str, source_name: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT, **_HEADERS})

    def close(self) -> None:
        self.session.close()

    def _get(self, path: str) -> Optional[str]:
        resp = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_paths(self, max_items: Optional[int] = None) -> Iterator[str]:
        page = 0
        count = 0
        seen = set()
        empty_pages = 0
        while empty_pages < 2:  # one repeat can happen mid-shuffle; two in a row means we've hit the clamp
            html = self._get(f"buscar/?type=&operation=&page={page}")
            if not html:
                break
            paths = _DETAIL_LINK_RE.findall(html)
            new_paths = [p for p in dict.fromkeys(paths) if p not in seen]
            if not new_paths:
                empty_pages += 1
                page += 1
                time.sleep(self.delay)
                continue
            empty_pages = 0
            for path in new_paths:
                seen.add(path)
                yield path
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
        for path in self.iter_paths(max_items=max_pages):
            item = self._scrape_detail(path)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, path: str) -> Optional[PropertyItem]:
        url = f"{self.base_url}{path}"
        html = self._get(path)
        if html is None:
            return None
        try:
            return self._normalize(path, url, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, url)
            return None

    def _normalize(self, path: str, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        id_match = re.search(r"-(\d+)-(\d+)$", path)
        if not id_match:
            return None
        source_id = id_match.group(2)

        page_root = soup.select_one("div.page.page-property") or soup

        title_el = page_root.find("h1")
        title = title_el.get_text(strip=True) if title_el else None

        h2_el = page_root.find("h2")
        address = None
        if h2_el:
            h2_text = h2_el.get_text(" ", strip=True)
            parts = h2_text.split("|", 1)
            if len(parts) == 2:
                address = parts[1].strip()

        price_el = page_root.select_one(".price.nota")
        currency, price = _parse_price(price_el.get_text(strip=True) if price_el else "")

        op_match = _OPERATION_RE.search(path)
        operation = {"venta": "sale", "alquiler": "rent"}.get(op_match.group(1) if op_match else "", "sale")

        desc_el = page_root.select_one(".description p")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        fields = {}
        for row in page_root.select("#details table tr"):
            label_el = row.select_one("td.bold")
            value_el = row.select_one("td.body")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).rstrip(":")
            value = value_el.get_text(strip=True)
            if label and value:
                fields[label] = value

        mapped = {}
        for label, value in fields.items():
            label_lower = label.lower()
            for pattern, dest_key in _DETAIL_FIELD_PATTERNS:
                if pattern.search(label_lower):
                    if dest_key in ("total_m2", "covered_m2", "land_m2"):
                        mapped[dest_key] = _to_float(value)
                    elif dest_key in ("bedrooms", "bathrooms", "total_rooms"):
                        mapped[dest_key] = _first_int(value)
                    break

        photos = [a.get("href") for a in page_root.select("#photos .ad-thumb-list a[href]") if a.get("href")]

        phone_input = page_root.select_one('input[name="branchPhones"]')
        phone = phone_input.get("value") if phone_input else None

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            description=description,
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            total_m2=mapped.get("total_m2"),
            covered_m2=mapped.get("covered_m2"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            total_rooms=mapped.get("total_rooms"),
            agent_name=self.source_name,
            agent_phone=phone,
            office_name=self.source_name,
            photos=photos,
            raw=fields,
        )


def _parse_price(text: str):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.match(r"(?:Valor:\s*)?([A-Za-z$]+)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if "usd" in currency_raw.lower() else ("ARS" if "$" in currency_raw else currency_raw.upper())
    return currency, _to_float(number_raw)


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = re.match(r"\s*([\d.,]+)", value)
    if not m:
        return None
    number = m.group(1)
    cleaned = number.replace(".", "").replace(",", ".") if "," in number else number.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None
