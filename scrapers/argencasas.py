"""Generic scraper for agency websites built on the "ArgenCasas" white-label
real-estate CMS (api.argencasas.com backend) — a platform used by many small
Argentine real-estate agencies for their own public sites.

Discovered via Ferrero Propiedades (inmobiliariaferrero.com, Ituzaingó): each
agency site is a thin, unprotected (no robots.txt, no Cloudflare/WAF) PHP
frontend over the shared ArgenCasas backend. Two things make it easy to
scrape reliably:

1. Listing pages (`/venta/propiedades`, `/alquiler/propiedades`, paginated as
   `/pag-N`) are plain server-rendered HTML with `<div id='{inmobId}-{propId}'
   class='prop-item'>` cards linking to `/ficha/{inmobId}-{propId}`.
2. Each detail ("ficha") page embeds the *entire* raw property record as a
   hidden PHP `var_dump()` (`<pre style='display:none'>...`) — clearly a
   debug leftover, but it hands us clean typed fields (floats for lat/lon,
   ints for price/m²/rooms, the full photo array) instead of having to
   scrape rendered text.

Since this is one platform under many domains, this class takes `base_url`
and `source_name` per agency rather than hardcoding one site — Ferrero is
the first instance; more agencies on the same platform can be added as a
one-line subclass/registration.
"""

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

OPERATION_MAP = {
    "venta": "sale",
    "alquiler": "rent",
    "alquiler temporal": "temporal",
}

_ITEM_ID_RE = re.compile(r"id='(\d+-\d+)'\s+class='prop-item'")
_VARDUMP_RE = re.compile(r"<pre style='display:none'>(object\(stdClass\)#.*?)</pre>", re.S)


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": config.USER_AGENT})
    return session


class ArgenCasasScraper(BaseScraper):
    all_in_one = True  # both operations are discovered from separate listing sections in one pass

    def __init__(self, base_url: str, source_name: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = _make_session()

    def close(self) -> None:
        self.session.close()

    def _get(self, path: str) -> Optional[str]:
        resp = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_ids(self, section: str, max_items: Optional[int] = None) -> Iterator[str]:
        """section: 'venta/propiedades' or 'alquiler/propiedades'."""
        page = 1
        count = 0
        while True:
            path = section if page == 1 else f"{section}/pag-{page}"
            html = self._get(path)
            if not html:
                break
            ids = _ITEM_ID_RE.findall(html)
            if not ids:
                break
            for item_id in ids:
                yield item_id
                count += 1
                if max_items is not None and count >= max_items:
                    return
            if "pagination__next" not in html:
                break
            page += 1
            time.sleep(self.delay)

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        seen = set()
        for section in ("venta/propiedades", "alquiler/propiedades"):
            for item_id in self.iter_ids(section, max_items=max_pages):
                if item_id in seen:
                    continue
                seen.add(item_id)
                item = self._scrape_detail(item_id)
                if item is None:
                    continue
                if operation != "all" and item.operation != operation:
                    continue
                yield item
                time.sleep(self.delay)

    def _scrape_detail(self, item_id: str) -> Optional[PropertyItem]:
        html = self._get(f"/ficha/{item_id}")
        if html is None:
            return None
        try:
            return self._normalize(item_id, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, item_id)
            return None

    def _normalize(self, item_id: str, html: str) -> Optional[PropertyItem]:
        dump_match = _VARDUMP_RE.search(html)
        data = _parse_php_vardump(dump_match.group(1)) if dump_match else {}

        operacion_match = re.search(r"class=\"operacion\">\s*([^<\n]+?)\s*</div>", html)
        tipo_match = re.search(r"class=\"tipo\">\s*([^<\n]+?)\s*</div>", html)
        address_match = re.search(r"<h1 class='underlined'><span>([^<]+)</span>", html)
        price_match = re.search(r"class=\"price\">\s*([A-Za-z$]+)\s*([\d.,]+)", html)
        whatsapp_match = re.search(r"https://wa\.me/(\d+)", html)

        operation_raw = (operacion_match.group(1).strip().lower() if operacion_match else "")
        operation = OPERATION_MAP.get(operation_raw, "sale")
        property_type = tipo_match.group(1).strip() if tipo_match else None

        address, _, zone = (address_match.group(1).partition(" / ") if address_match else (None, None, None))

        currency = price = None
        if price_match:
            currency = "USD" if "u" in price_match.group(1).lower() else "ARS"
            price = _to_float(price_match.group(2))
        elif data.get("valor") is not None:
            price = float(data["valor"])

        return PropertyItem(
            source=self.source_name,
            source_id=item_id,
            url=f"{self.base_url}/ficha/{item_id}",
            title=f"{property_type or ''} en {operation_raw or ''} - {address or ''}".strip(" -"),
            description=data.get("descripcion"),
            property_type=property_type,
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            neighborhood=zone or None,
            city=None,
            province=None,
            lat=data.get("latitud"),
            lon=data.get("longitud"),
            total_rooms=data.get("ambientes"),
            bedrooms=data.get("dormitorios"),
            bathrooms=data.get("banios"),
            land_m2=data.get("sup_libre"),
            covered_m2=data.get("sup_cubierta"),
            total_m2=data.get("sup_total"),
            agent_name=self.source_name,
            agent_phone=whatsapp_match.group(1) if whatsapp_match else None,
            office_name=self.source_name,
            photos=data.get("imagenes") or [],
            raw=data,
        )


def _to_float(value: str) -> Optional[float]:
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".") if "," in value else value.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_php_vardump(text: str) -> dict:
    """Minimal parser for the flat fields we care about in a PHP var_dump()
    of a stdClass — not a general-purpose var_dump parser, just enough to
    pull out scalars and the one string array (imagenes) this page emits."""
    result: dict = {}

    for m in re.finditer(r'\["(\w+)"\]=>\s*(?:int|float)\(([-\d.]+)\)', text):
        key, value = m.groups()
        result[key] = float(value) if "." in value else int(value)

    for m in re.finditer(r'\["(\w+)"\]=>\s*string\(\d+\)\s*"((?:[^"\\]|\\.)*)"', text, re.S):
        key, value = m.groups()
        result[key] = value.replace('\\"', '"')

    images_match = re.search(r'\["imagenes"\]=>\s*array\(\d+\)\s*\{(.*?)\n  \}', text, re.S)
    if images_match:
        result["imagenes"] = re.findall(r'string\(\d+\)\s*"([^"]+)"', images_match.group(1))

    return result
