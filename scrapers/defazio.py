"""De Fazio Inmobiliaria (Ciudadela, Tres de Febrero) — custom Next.js
frontend over a Xintel backend (photos on `cdn-images.xintelweb.com`, same
CDN family as Grupo Vaccaro/Gabriel Paris/Amaira), but NOT the
`{base}/api/proxy.php` variant `scrapers/fparadela.py` already handles —
that route 404s here. No API access found (no `/api/properties` route
either); `/propiedades` instead server-renders all ~260 listings inline in
one ~2.6MB HTML page, no pagination needed.

Card fields aren't cleanly nested for BeautifulSoup ancestor traversal (the
image `<a>` and the text `<div>` are siblings, not parent/child, and
`find_parent` couldn't find a shared card container reliably) — parsed via
regex on raw HTML instead, splitting on the repeated `/propiedades/DEF{id}`
href (it appears exactly twice per card — once on the image link, once on
the "Ver propiedad" button — so every *other* match is a card boundary).

The <h2> field is unreliable as a title — depending on the listing it holds
a street address ("manuel gallardo 451"), a route name ("RUTA NAC. 9"), or
just a lone digit ("1", seemingly a unit/lot number on multi-unit listings)
— so title comes from the photo's `alt` text instead ("Edificio en venta
Versalles"), which is consistently well-formed; <h2> is kept as `address`
since that's still what the site itself labels it as, imperfect or not.
"""

import html as html_module
import logging
import re
import time
from typing import Iterator, Optional
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

BASE_URL = "https://defazioprop.com.ar"

_ID_RE = re.compile(r'href="/propiedades/(DEF\d+)"')
_ALT_RE = re.compile(r'alt="([^"]*)"')
_PHOTO_RE = re.compile(r"cdn-images\.xintelweb\.com%2Fupload%2F([a-z0-9_]+\.jpe?g)")
_OPERATION_BADGE_RE = re.compile(r'class="absolute left-4 top-4[^"]*">([^<]+)</span>')
_PRICE_RE = re.compile(r'class="text-3xl font-black[^"]*">([^<]+)</p>')
_M2_RE = re.compile(r"([\d.,]+)\s*m²\s*tot\.")
_AMB_RE = re.compile(r">(\d+)<!-- -->\s*amb\.")
_DORM_RE = re.compile(r">(\d+)\s*dorm\.")
_BANO_RE = re.compile(r">(\d+)\s*ba[ñn]o")
_H2_RE = re.compile(r'class="mt-4 text-xl font-black[^"]*">([^<]*)</h2>')
_LOCATION_RE = re.compile(r"lucide-map-pin[\s\S]*?</svg>([^<]+)</p>")
_DESC_RE = re.compile(r'class="mt-4 line-clamp-2[^"]*">([^<]*)</p>')

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}


class DeFazioScraper(BaseScraper):
    source_name = "defazio"
    all_in_one = True

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        resp = self.session.get(f"{BASE_URL}/propiedades", timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        positions = [m.start() for m in _ID_RE.finditer(html)]
        card_starts = positions[0::2]  # id href appears twice per card; every other match starts a new card
        count = 0
        for i, start in enumerate(card_starts):
            end = card_starts[i + 1] if i + 1 < len(card_starts) else len(html)
            chunk = html[start:end]
            item = self._parse_card(chunk)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            count += 1
            if max_pages is not None and count >= max_pages:
                return
            time.sleep(0)  # no per-item request — whole catalog came in one page fetch

    def _parse_card(self, chunk: str) -> Optional[PropertyItem]:
        try:
            return self._normalize(chunk)
        except Exception:
            logger.exception("Failed to parse defazio card")
            return None

    def _normalize(self, chunk: str) -> Optional[PropertyItem]:
        id_match = _ID_RE.search(chunk)
        if not id_match:
            return None
        source_id = id_match.group(1)
        url = f"{BASE_URL}/propiedades/{source_id}"

        alt_match = _ALT_RE.search(chunk)
        title = html_module.unescape(alt_match.group(1)).strip() if alt_match else None

        badge_match = _OPERATION_BADGE_RE.search(chunk)
        operation_raw = badge_match.group(1).strip().lower() if badge_match else ""
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        price_match = _PRICE_RE.search(chunk)
        currency, price = _parse_price(price_match.group(1) if price_match else "")

        h2_match = _H2_RE.search(chunk)
        address = html_module.unescape(h2_match.group(1)).strip() or None if h2_match else None

        location_match = _LOCATION_RE.search(chunk)
        location = html_module.unescape(location_match.group(1)).strip() if location_match else ""
        neighborhood, _, city = location.partition("·")  # middle dot (U+00B7), not a hyphen/en dash
        neighborhood = neighborhood.strip() or None
        city = city.strip() or (location or None)

        desc_match = _DESC_RE.search(chunk)
        description = html_module.unescape(desc_match.group(1)).strip() if desc_match else None

        m2_match = _M2_RE.search(chunk)
        amb_match = _AMB_RE.search(chunk)
        dorm_match = _DORM_RE.search(chunk)
        bano_match = _BANO_RE.search(chunk)

        photo_matches = dict.fromkeys(_PHOTO_RE.findall(chunk))
        photos = [f"https://cdn-images.xintelweb.com/upload/{unquote(p)}" for p in photo_matches]

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
            neighborhood=neighborhood,
            city=city,
            total_rooms=int(amb_match.group(1)) if amb_match else None,
            bedrooms=int(dorm_match.group(1)) if dorm_match else None,
            bathrooms=int(bano_match.group(1)) if bano_match else None,
            total_m2=_to_float(m2_match.group(1)) if m2_match else None,
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw={},
        )


def _parse_price(text: str):
    text = (text or "").strip()
    m = re.match(r"(USD|ARS|\$)\s*([\d.,]+)", text, re.IGNORECASE)
    if not m:
        return None, None
    currency = "USD" if m.group(1).upper() == "USD" else "ARS"
    return currency, _to_float(m.group(2))


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    number = value.strip()
    cleaned = number.replace(".", "").replace(",", ".") if "," in number else number.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
