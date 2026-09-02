"""Generic scraper for agency sites built on the "Houzez" WordPress real
estate theme (houzez.io) — an extremely common choice for small/independent
agencies (recognizable by `houzez-icon` classes, a `houzez_single_property_map`
inline JS object, and a `property-sitemap.xml` from Yoast SEO's CPT sitemap).

Discovered via Morroni Propiedades (morronipropiedades.com.ar, Morón). Same
idea as scrapers/argencasas.py: one adapter, `base_url` per agency.

Discovery uses the WordPress/Yoast sitemap (`sitemap_index.xml` -> the
`*property-sitemap*.xml` entries) rather than paginating search results —
simpler, and robots.txt on Houzez sites is typically wide open (Yoast's
default, no disallow rules relevant to this).

Each detail page embeds a clean inline JS object,
`houzez_single_property_map = {...}`, with title/price/id/address/lat/lng —
valid JSON, no HTML scraping needed for those fields. Everything else (m²,
rooms, bathrooms, property type, description, gallery, agent phone) comes
from Houzez's own consistently-classed markup (`ul.list-2-cols li`,
`#property-description-wrap`, `.houzez-trigger-popup-slider-js img`, etc.)
shared across every Houzez site regardless of agency.
"""

import json
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

_MAP_JS_RE = re.compile(r"var houzez_single_property_map\s*=\s*(\{.*?\});", re.S)

# Every Houzez install lets the agency reword the "Detalles" labels and pick
# how many columns the list renders in (list-1-cols / list-2-cols / ...), so
# neither the label text nor that class name is reliable across sites —
# match by pattern against a normalized (lowercased, period-stripped) label
# instead of an exact dict lookup. Order matters: more specific patterns
# (land, which also contains a m² label) must be checked before the generic
# "total" one.
_DETAIL_FIELD_PATTERNS = [
    (re.compile(r"terreno"), "land_m2"),
    (re.compile(r"cubiert"), "covered_m2"),
    (re.compile(r"\btotal\b"), "total_m2"),
    (re.compile(r"dormitorio"), "bedrooms"),
    (re.compile(r"ambiente"), "total_rooms"),
    (re.compile(r"^ba[ñn]o"), "bathrooms"),
    (re.compile(r"^tipo\b(?!.*cochera)"), "property_type"),
]


class HouzezScraper(BaseScraper):
    all_in_one = True  # sitemap discovery mixes operations; operation comes from each page itself

    def __init__(self, base_url: str, source_name: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        })

    def close(self) -> None:
        self.session.close()

    def _get(self, url: str) -> Optional[str]:
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_urls(self, max_items: Optional[int] = None) -> Iterator[str]:
        index_xml = self._get(f"{self.base_url}/sitemap_index.xml")
        sub_sitemaps = []
        if index_xml:
            sub_sitemaps = [
                loc for loc in re.findall(r"<loc>(.*?)</loc>", index_xml) if "property-sitemap" in loc
            ]

        count = 0
        if sub_sitemaps:
            for sitemap_url in sub_sitemaps:
                xml = self._get(sitemap_url)
                if not xml:
                    continue
                for url in re.findall(r"<loc>(.*?)</loc>", xml):
                    if url.rstrip("/").endswith(("/propiedad", "/property")):
                        continue  # the CPT archive root, not an actual listing
                    yield url
                    count += 1
                    if max_items is not None and count >= max_items:
                        return
            return

        # no Yoast sitemap (not every Houzez site runs Yoast) — fall back to
        # paginating the property archive itself and pulling card links
        page = 1
        seen = set()
        while True:
            path = "propiedad/" if page == 1 else f"propiedad/page/{page}/"
            html = self._get(f"{self.base_url}/{path}")
            if not html:
                break
            urls = re.findall(r'<h2 class="item-title">\s*<a href="([^"]+)"', html)
            new_urls = [u for u in dict.fromkeys(urls) if u not in seen]
            if not new_urls:
                break
            for url in new_urls:
                seen.add(url)
                yield url
                count += 1
                if max_items is not None and count >= max_items:
                    return
            if f"page/{page + 1}" not in html:
                break
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
        soup = BeautifulSoup(html, "lxml")

        map_match = _MAP_JS_RE.search(html)
        map_data = json.loads(map_match.group(1)) if map_match else {}
        source_id = map_data.get("property_id") or re.search(r"data-propid=\"(\d+)\"", html)
        if isinstance(source_id, re.Match):
            source_id = source_id.group(1)
        if not source_id:
            return None

        title_el = soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else map_data.get("title")

        status_el = soup.select_one("a.label-status")
        operation_raw = (status_el.get_text(strip=True).lower() if status_el else "")
        operation = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}.get(operation_raw, "sale")

        price_el = soup.select_one("li.item-price")
        currency, price = _parse_price(price_el.get_text(" ", strip=True) if price_el else map_data.get("price", ""))

        fields = {}
        for li in soup.select("#property-detail-wrap .detail-wrap ul li"):
            strong = li.find("strong")
            span = li.find("span")
            if not strong or not span:
                continue
            label = strong.get_text(strip=True).rstrip(":").lower()
            fields[label] = span.get_text(strip=True)

        addr_fields = {}
        for li in soup.select("#property-address-wrap ul li"):
            classes = li.get("class") or []
            strong = li.find("strong")
            span = li.find("span")
            if not strong or not span:
                continue
            key = classes[0].replace("detail-", "") if classes else strong.get_text(strip=True).lower()
            addr_fields[key] = span.get_text(strip=True)

        desc_el = soup.select_one("#property-description-wrap .block-content-wrap")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        photos = [
            img.get("src")
            for img in soup.select("a.houzez-trigger-popup-slider-js img")
            if img.get("src")
        ]

        phone_el = soup.select_one('a[href^="tel:"]')
        phone = None
        if phone_el:
            # some installs put garbage (emoji, multiple numbers) in the tel:
            # href itself — keep only the first run of phone-ish characters
            digits_match = re.search(r"[\d+()-]{6,}", phone_el["href"].replace("tel:", ""))
            phone = digits_match.group(0) if digits_match else None

        mapped = {}
        for label, value in fields.items():
            dest = next((d for pattern, d in _DETAIL_FIELD_PATTERNS if pattern.search(label)), None)
            if not dest or dest in mapped:
                continue  # first match wins — patterns are ordered specific-to-generic
            if dest in ("land_m2", "covered_m2", "total_m2"):
                mapped[dest] = _to_float(value)
            elif dest in ("bedrooms", "bathrooms", "total_rooms"):
                mapped[dest] = _first_int(value)
            else:
                mapped[dest] = value

        return PropertyItem(
            source=self.source_name,
            source_id=str(source_id),
            url=url,
            title=title,
            description=description,
            property_type=mapped.get("property_type"),
            operation=operation,
            price=price,
            currency=currency,
            address=addr_fields.get("address") or map_data.get("address"),
            neighborhood=addr_fields.get("area"),
            city=addr_fields.get("city"),
            province=None,
            lat=_plain_float(map_data.get("lat")),
            lon=_plain_float(map_data.get("lng")),
            total_rooms=mapped.get("total_rooms"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            land_m2=mapped.get("land_m2"),
            covered_m2=mapped.get("covered_m2"),
            total_m2=mapped.get("total_m2"),
            agent_phone=phone,
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw={"fields": fields, "address": addr_fields, "map": map_data},
        )


def _parse_price(text: str):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.search(r"(USD|ARS|\$)\s*\$?\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if currency_raw == "USD" else "ARS"
    return currency, _to_float(number_raw)


def _to_float(value) -> Optional[float]:
    """Argentine-formatted number (dot = thousands separator, comma = decimal
    point) — e.g. price and m² fields. Not for lat/lng, see _plain_float.

    Without a comma present the dot is ambiguous ("9.500" is nine thousand
    five hundred, but Houzez renders m² as e.g. "95.00" — ninety-five).
    Disambiguate using the last dot-separated group's length: Argentine
    thousands groups are always exactly 3 digits, so a trailing group of 1-2
    digits means the dot is a decimal point instead.
    """
    if value is None:
        return None
    value = str(value)
    m = re.match(r"\s*(-?[\d.,]+)", value)
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
    """For values that are already plain decimal strings (JSON-sourced, dot
    as the decimal point, no thousands grouping) — e.g. lat/lng — unlike
    Argentine-formatted numbers (_to_float), which use dot as a thousands
    separator."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None
