"""Scarinci Propiedades (Sáenz Peña, Tres de Febrero) — WordPress + the
Realtyna WPL Pro plugin (new platform, not previously in this project).

WPL doesn't expose a WordPress REST custom post type (unlike RealHomes), and
its listing archive (`/en-venta/`, `/inmuebles-en-alquiler/`) ignores
WordPress's native `/page/N/` pagination entirely — both page 1 and page 2
of that URL scheme render identically. The real pagination lives in the
plugin's own client-side JS (`window.wpl_paginate`), which — on this site,
where `window.wpl_ajax == '0'` — just reloads the SAME archive URL with two
extra query params: `wplview=property_listing&sf_select_listing={N}` where
N is a per-listing-type id (9 = venta, 10 = alquiler, found by inspecting
`window.wpl_listing_request_str` in a real browser) plus `wplpage={page}`.
Requesting a page past the end doesn't return empty — it silently falls
back to rendering nav-menu HTML that happens to contain an "inmueble"
substring in an unrelated link (`/inmuebles-en-alquiler/`) — so discovery
must match the precise detail-page pattern `inmueble/\\d+-...` (a real
listing always has a numeric id right after the slash), not just any href
containing "inmueble", or that false positive never lets the loop end.

Detail pages (`/inmueble/{id}-{slug}/`) render every field as
`<div class="wpl-column rows ...">Label : <span>Value</span></div>` — clean
and uniform, parsed with a single "Label : <span>Value</span>" regex per
field wanted, no per-platform HTML archaeology needed beyond finding this
pattern once. Photos are `/wp-content/uploads/WPL/{id}/thimg_*.jpg`.

One unrelated oddity found while mapping a detail page: the surrounding
site HTML has a handful of "réplicas de relojes rolex" spam links injected
somewhere in the page chrome — looks like an SEO-spam compromise of some
plugin/theme file, unrelated to and not interfering with the WPL listing
data itself. Noted here in case it resurfaces as a bigger problem later;
not something this scraper needs to work around.
"""

import html as html_module
import logging
import re
import time
from typing import Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

BASE_URL = "https://scarincipropiedades.com.ar"

_LISTING_TYPES = {
    "sale": ("en-venta", 9),
    "rent": ("inmuebles-en-alquiler", 10),
}

_DETAIL_HREF_RE = re.compile(r'href="(https://scarincipropiedades\.com\.ar/inmueble/(\d+)-[^"]+)"')


def _field_re(label: str) -> re.Pattern:
    return re.compile(rf"{re.escape(label)}\s*:\s*<span>([^<]*)</span>", re.IGNORECASE)


_FIELD_PATTERNS = {
    "property_type": _field_re("Tipo de inmueble"),
    "price_text": _field_re("Precio"),
    "expenses_text": _field_re("Expensas"),
    "total_rooms": _field_re("Ambientes"),
    "bedrooms": _field_re("Dormitorios"),
    "bathrooms": _field_re("Baños"),
    "covered_m2": _field_re("Superficie cubierta"),
    "land_m2": _field_re("Superficie del terreno"),
    "province": _field_re("Provincia"),
    "city": _field_re("Ciudad"),
}

_TITLE_RE = re.compile(r'class="title_text"[^>]*>([^<]*)</h1>')
_DESC_RE = re.compile(r'wpl_category_description">([\s\S]*?)</div>\s*</div>')
_PHOTO_RE = re.compile(r'/wp-content/uploads/WPL/(\d+)/thimg_[^"]+\.jpe?g')


class ScarinciScraper(BaseScraper):
    source_name = "scarinci"
    all_in_one = False  # separate sf_select_listing id per operation, easiest to loop explicitly

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _iter_urls_for(self, operation: str, max_items: Optional[int] = None) -> Iterator[tuple]:
        slug, sf_id = _LISTING_TYPES[operation]
        seen = set()
        page = 1
        count = 0
        while True:
            resp = self.session.get(
                f"{BASE_URL}/{slug}/",
                params={
                    "wplview": "property_listing",
                    "sf_select_listing": sf_id,
                    "wplpagination": "normal",
                    "wplpage": page,
                },
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            found = _DETAIL_HREF_RE.findall(resp.text)
            new = [(url, pid) for url, pid in found if pid not in seen]
            if not new:
                break
            for url, pid in new:
                seen.add(pid)
                yield url, pid
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
        operations = ["sale", "rent"] if operation == "all" else [operation]
        for op in operations:
            if op not in _LISTING_TYPES:
                continue
            for url, pid in self._iter_urls_for(op, max_items=max_pages):
                item = self._scrape_detail(url, pid, op)
                if item is not None:
                    yield item
                time.sleep(self.delay)

    def _scrape_detail(self, url: str, property_id: str, operation: str) -> Optional[PropertyItem]:
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        try:
            return self._normalize(url, property_id, operation, resp.text)
        except Exception:
            logger.exception("Failed to parse scarinci listing %s", url)
            return None

    def _normalize(self, url: str, property_id: str, operation: str, html: str) -> PropertyItem:
        def field(name: str) -> Optional[str]:
            m = _FIELD_PATTERNS[name].search(html)
            return html_module.unescape(m.group(1)).strip() if m else None

        title_match = _TITLE_RE.search(html)
        title = html_module.unescape(title_match.group(1)).strip() if title_match else None

        desc_match = _DESC_RE.search(html)
        description = None
        if desc_match:
            description = re.sub(r"<[^>]+>", "\n", desc_match.group(1))
            description = html_module.unescape(description)
            description = re.sub(r"\n{2,}", "\n\n", description).strip()
            if description.startswith("Descripcion"):
                description = description[len("Descripcion") :].strip()

        currency, price = _parse_price(field("price_text") or "")
        _, expenses_price = _parse_price(field("expenses_text") or "")

        photos = list(
            dict.fromkeys(
                f"{BASE_URL}{m.group(0)}" for m in _PHOTO_RE.finditer(html) if m.group(1) == property_id
            )
        )

        return PropertyItem(
            source=self.source_name,
            source_id=property_id,
            url=url,
            title=title,
            description=description,
            property_type=field("property_type"),
            operation=operation,
            price=price,
            currency=currency,
            expenses_price=expenses_price,
            city=field("city"),
            province=field("province"),
            total_rooms=_first_int(field("total_rooms")),
            bedrooms=_first_int(field("bedrooms")),
            bathrooms=_first_int(field("bathrooms")),
            covered_m2=_first_float(field("covered_m2")),
            land_m2=_first_float(field("land_m2")),
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw={},
        )


def _parse_price(text: str):
    text = (text or "").strip()
    m = re.match(r"(U\$S|USD|ARS|\$)\s*([\d.,]+)", text, re.IGNORECASE)
    if not m:
        return None, None
    currency_raw = m.group(1).upper()
    currency = "USD" if currency_raw in ("U$S", "USD") else "ARS"
    return currency, _to_float(m.group(2))


def _to_float(value: Optional[str]) -> Optional[float]:
    # This site formats numbers US-style ("U$S120,000") — comma is always a
    # thousands separator, period a decimal point, unlike the Argentine
    # "." thousands / "," decimal convention most other tenants use.
    if not value:
        return None
    number = value.strip().replace(",", "")
    try:
        return float(number)
    except ValueError:
        return None


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _first_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d.,]+", text)
    return _to_float(m.group()) if m else None
