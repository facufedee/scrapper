"""Fabiana M. Tripe Inmuebles (Castelar) — bespoke PHP site, not seen on any
other agency yet, so kept as a standalone scraper rather than a generic
platform adapter.

Listing (`/propiedades.php?page=N`) is server-rendered, `div.flex-item` cards
each with a "Consultá" `a.button[href]` linking to the detail page — the
href is a root-relative slug with no numeric id anywhere in it, so the slug
itself is used as `source_id` (stable as long as the site doesn't rename
listings, same tradeoff every slug-only source has to make).

Detail page has `.ficha-title`/`.ficha-price` for title+price+address, and
two parallel `<ul>` pairs (`.supp-table.first` = labels, `.supp-table` =
values, matched positionally) for the field table — much simpler than the
icon-keyed summary list above it, which duplicates the same numbers without
labels and is skipped as redundant. No robots.txt restrictions
(`Disallow:` is empty).
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

BASE_URL = "https://fabianamtripe.com.ar"

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

_DETAIL_FIELD_PATTERNS = [
    (re.compile(r"superficie terreno"), "land_m2"),
    (re.compile(r"superficie cubierta"), "covered_m2"),
    (re.compile(r"^ambiente"), "total_rooms"),
    (re.compile(r"^dormitorio"), "bedrooms"),
    (re.compile(r"^ba[ñn]o"), "bathrooms"),
]


class FabianaMTripeScraper(BaseScraper):
    source_name = "fabianamtripe"
    all_in_one = True  # /propiedades.php mixes venta+alquiler; operation is per-card/detail

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT, **_HEADERS})

    def close(self) -> None:
        self.session.close()

    def _get(self, path: str) -> Optional[str]:
        resp = self.session.get(f"{BASE_URL}/{path.lstrip('/')}", timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_paths(self, max_items: Optional[int] = None) -> Iterator[str]:
        page = 1
        count = 0
        seen = set()
        while True:
            html = self._get(f"propiedades.php?page={page}")
            if not html:
                break
            soup = BeautifulSoup(html, "lxml")
            paths = [
                a.get("href") for a in soup.select("div.flex-item a.button[href]")
                if a.get("href", "").startswith("/")
            ]
            new_paths = [p for p in dict.fromkeys(paths) if p not in seen]
            if not new_paths:
                break
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
        url = f"{BASE_URL}{path}"
        html = self._get(path)
        if html is None:
            return None
        try:
            return self._normalize(path, url, html)
        except Exception:
            logger.exception("Failed to parse fabianamtripe listing %s", url)
            return None

    def _normalize(self, path: str, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        source_id = path.lstrip("/")
        if not source_id:
            return None

        title_el = soup.select_one("h1.ficha-title")
        title = title_el.get_text(strip=True) if title_el else None

        price_el = soup.select_one("p.ficha-price")
        address = None
        currency = price = None
        if price_el:
            price_text = price_el.get_text(" ", strip=True)
            parts = price_text.split("|", 1)
            currency, price = _parse_price(parts[0])
            if len(parts) == 2:
                address = parts[1].strip()

        type_el = soup.select_one("span.flex-item-type")
        operation_raw = type_el.get_text(strip=True).lower() if type_el else ""
        operation = {"venta": "sale", "alquiler": "rent"}.get(operation_raw, "sale")

        desc_el = soup.select_one("p.text-15")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        fields = {}
        for label_ul, value_ul in zip(soup.select("ul.supp-table.first"), soup.select("ul.supp-table:not(.first)")):
            labels = [li.get_text(strip=True) for li in label_ul.find_all("li")]
            values = [li.get_text(strip=True) for li in value_ul.find_all("li")]
            for label, value in zip(labels, values):
                if label and value and value != "-":
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

        photos = [
            img.get("src") for img in soup.select("div.item img[src]")
            if img.get("src")
        ]
        photos = [p if p.startswith("http") else f"{BASE_URL}/{p.lstrip('/')}" for p in photos]

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
            land_m2=mapped.get("land_m2"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            total_rooms=mapped.get("total_rooms"),
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw=fields,
        )


def _parse_price(text: str):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.match(r"([A-Za-z$]+)\s*([\d.,]+)", text)
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
