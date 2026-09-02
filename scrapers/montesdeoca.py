"""Montes de Oca (General San Martín, borders Tres de Febrero) — WordPress
with the JetEngine plugin's `propiedades` custom post type.

Unlike RealHomes, this JetEngine install doesn't register its custom fields
(price, m², rooms) for REST exposure — `/wp-json/wp/v2/propiedades` gives
id/title/link/date and two taxonomy id lists (`estado` = operation,
`tipo` = property type) but nothing else useful. So discovery + operation/
property_type come from the REST API (paginated, cheap), while price/
address/description/rooms/photos are scraped from each detail page's HTML,
where JetEngine renders every custom field as an identically-classed
`.jet-listing-dynamic-field` div with no way to tell them apart except by
field ORDER and text-prefix pattern (same style as the "Label: value" rows
navent_ficha.py's Cabrera/Franco fallback already parses) — order observed:
price, price (duplicate), address, description, ambientes (x2), dormitorios,
baños, lavadero, terreno m2, cubierto m2, descubierto m2, servicios, código.
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

BASE_URL = "https://montesdeocaprop.com.ar"
API_BASE = f"{BASE_URL}/wp-json/wp/v2"

_LABELED_FIELD_PATTERNS = [
    (re.compile(r"terreno:?\s*([\d.,]+)\s*m", re.IGNORECASE), "land_m2"),
    (re.compile(r"cubiert[oa]:?\s*([\d.,]+)\s*m", re.IGNORECASE), "covered_m2"),
    (re.compile(r"descubiert[oa]:?\s*([\d.,]+)\s*m", re.IGNORECASE), "total_m2"),
    (re.compile(r"ambientes?:?\s*(\d+)", re.IGNORECASE), "total_rooms"),
    (re.compile(r"dormitorios?:?\s*(\d+)", re.IGNORECASE), "bedrooms"),
    (re.compile(r"ba[ñn]os?:?\s*(\d+)", re.IGNORECASE), "bathrooms"),
]


class MontesDeOcaScraper(BaseScraper):
    source_name = "montesdeoca"
    all_in_one = True

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})
        self._estado_map: Optional[dict] = None
        self._tipo_map: Optional[dict] = None

    def close(self) -> None:
        self.session.close()

    def _get_json(self, url: str, params: dict):
        resp = self.session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
        # WP REST returns 400 (rest_post_invalid_page_number), not an empty
        # array, once `page` exceeds the collection's last page — that's the
        # normal "no more results" signal for this endpoint, not an error.
        if resp.status_code in (404, 400):
            return None
        resp.raise_for_status()
        return resp.json()

    def _taxonomy_map(self, taxonomy: str) -> dict:
        terms = self._get_json(f"{API_BASE}/{taxonomy}", {"per_page": 100}) or []
        return {t["id"]: t["name"] for t in terms}

    def iter_posts(self, max_items: Optional[int] = None) -> Iterator[dict]:
        page = 1
        count = 0
        while True:
            posts = self._get_json(f"{API_BASE}/propiedades", {"page": page, "per_page": 50})
            if not posts:
                break
            for post in posts:
                yield post
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
        if self._estado_map is None:
            self._estado_map = self._taxonomy_map("estado")
        if self._tipo_map is None:
            self._tipo_map = self._taxonomy_map("tipo")

        for post in self.iter_posts(max_items=max_pages):
            item = self._scrape_detail(post)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, post: dict) -> Optional[PropertyItem]:
        url = post.get("link")
        if not url:
            return None
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return self._normalize(post, url, resp.text)
        except Exception:
            logger.exception("Failed to parse montesdeoca listing %s", url)
            return None

    def _normalize(self, post: dict, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        estado_names = [self._estado_map.get(i, "").lower() for i in post.get("estado") or []]
        operation = "sale"
        if any("alquiler temp" in e for e in estado_names):
            operation = "temporal"
        elif any("alquiler" in e for e in estado_names):
            operation = "rent"
        elif any("venta" in e for e in estado_names):
            operation = "sale"

        tipo_names = [self._tipo_map.get(i) for i in post.get("tipo") or [] if self._tipo_map.get(i)]
        property_type = tipo_names[0] if tipo_names else None

        fields = [
            d.get_text(" ", strip=True) for d in soup.select(".jet-listing-dynamic-field") if d.get_text(strip=True)
        ]

        # Money-amount fields (there are usually 2+: the headline price, an
        # "alquiler $X" expenses/rent aside, an "expensas $X" line) all need
        # excluding from the address/description guesses below, not just
        # the first one, or a second $-amount gets misread as the address.
        money_re = re.compile(r"(USD|U\$D|ARS|\$)\s*[\d,]+", re.IGNORECASE)
        price = currency = None
        remaining = []
        for text in fields:
            money_match = money_re.search(text)
            if money_match:
                if price is None:
                    currency, price = _parse_price(money_match.group())
                continue
            remaining.append(text)

        address = None
        description = None
        mapped: dict = {}
        for text in remaining:
            matched_field = False
            for pattern, dest_key in _LABELED_FIELD_PATTERNS:
                m = pattern.search(text)
                if not m:
                    continue
                matched_field = True
                if dest_key in ("total_m2", "covered_m2", "land_m2"):
                    mapped.setdefault(dest_key, _to_float(m.group(1)))
                else:
                    mapped.setdefault(dest_key, int(m.group(1)))
                break
            if matched_field or text.upper().startswith("CÓDIGO") or text.upper().startswith("CODIGO"):
                continue
            if address is None and len(text) < 80 and "," in text:
                address = text
                continue
            if description is None and len(text) > 80:
                description = text

        photos = [
            img.get("src")
            for img in soup.select('img[src*="wp-content/uploads"]')
            if img.get("src") and "logo" not in img.get("src", "").lower()
        ]

        title_html = (post.get("title") or {}).get("rendered", "")
        title = BeautifulSoup(title_html, "lxml").get_text(strip=True) or None

        return PropertyItem(
            source=self.source_name,
            source_id=str(post["id"]),
            url=url,
            title=title,
            description=description,
            property_type=property_type,
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            total_rooms=mapped.get("total_rooms"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            land_m2=mapped.get("land_m2"),
            covered_m2=mapped.get("covered_m2"),
            total_m2=mapped.get("total_m2"),
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw={"estado": post.get("estado"), "tipo": post.get("tipo")},
        )


def _parse_price(text: str):
    # This site's price fields are always "USD118,000" / "$160,000" — comma
    # as a thousands separator, US-style, never a decimal (unlike the "."
    # thousands / "," decimal convention _to_float below handles for the
    # m²/room fields, which come from a different, Argentine-formatted
    # source string).
    text = (text or "").strip()
    m = re.match(r"(USD|U\$D|ARS|\$)\s*([\d,]+)", text, re.IGNORECASE)
    if not m:
        return None, None
    currency_raw = m.group(1).upper()
    currency = "USD" if "USD" in currency_raw or "U$D" in currency_raw else "ARS"
    try:
        return currency, float(m.group(2).replace(",", ""))
    except ValueError:
        return currency, None


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    number = value.strip()
    cleaned = number.replace(".", "").replace(",", ".") if "," in number else number.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
