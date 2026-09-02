"""Generic scraper for agency sites built on a licensed Navent "ficha"
template (`busca_prop.php`/`detalle-item.php`) — found via Ledesma
Propiedades, generalized after confirming Inmobiliaria Cabrera and Franco
Property Organization run the exact same backend.

Signals: Navent-brand icon glyphs in the detail-page CSS
(icon-g-logo-zonaprop, icon-g-logo-adondevivir, etc., asset version string
"RPFICv4.1.2-RC1") and photos hosted on `inmomap.com.ar`.

The `co={tenant}` query param looks like a per-tenant code at first glance,
but isn't: every confirmed tenant's own site accepts `co=PD` (Ledesma's
code) and still returns that tenant's own distinct inventory — tenancy is
by domain, `co` is inert template boilerplate nobody bothered to
parametrize. Kept as a constructor arg (defaulting to "PD") in case some
future tenant's install DOES require its own value, but don't expect to
need it.

Listing (`busca_prop.php?tipo_operacion={Venta|Alquiler|Alquiler Temporal}&
posicion_actual=N&co={tenant_code}&...`) pages 16 items at a time via a
`buscar_prop_gral(N)` JS pagination control — `posicion_actual` is the same
param already on the page, just increasing by 16 (page size) each step.
Detail fields (`div.largo`) bundle label and value into one string per div
("Superficie Cubierta 73 m2", "2 Dormitorios") rather than clean label/value
pairs, so they're parsed with per-field regexes instead of a lookup table.
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

PAGE_SIZE = 16

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

_OPERATION_MAP = {"Venta": "sale", "Alquiler": "rent", "Alquiler Temporal": "temporal"}

_FIELD_PATTERNS = [
    (re.compile(r"superficie\s*cubierta\s*([\d.,]+)\s*m", re.IGNORECASE), "covered_m2"),
    (re.compile(r"superficie\s*total\s*([\d.,]+)\s*m", re.IGNORECASE), "total_m2"),
    (re.compile(r"^(\d+)\s*(?:o\s*mas\s*)?ambientes?", re.IGNORECASE), "total_rooms"),
    (re.compile(r"^(\d+)\s*dormitorios?", re.IGNORECASE), "bedrooms"),
    (re.compile(r"^(\d+)\s*ba[ñn]o", re.IGNORECASE), "bathrooms"),
]

# Same backend, but some tenant installs (Cabrera, Franco) run a frontend
# skin with "Label: value" ordering instead of Ledesma's "value label" divs
# — a second pattern set, tried only when the first finds nothing.
_LABELED_FIELD_PATTERNS = [
    (re.compile(r"sup\.?\s*cubiert[ao]:?\s*([\d.,]+)", re.IGNORECASE), "covered_m2"),
    (re.compile(r"sup\.?\s*total:?\s*([\d.,]+)", re.IGNORECASE), "total_m2"),
    (re.compile(r"cant\.?\s*amb:?\s*(\d+)", re.IGNORECASE), "total_rooms"),
    (re.compile(r"dormitorios?:?\s*(\d+)", re.IGNORECASE), "bedrooms"),
    (re.compile(r"ba[ñn]os?:?\s*(\d+)", re.IGNORECASE), "bathrooms"),
]


class NaventFichaScraper(BaseScraper):
    all_in_one = True  # loops all 3 operations itself when called with operation="all"

    def __init__(self, base_url: str, source_name: str, tenant_code: str = "PD", delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.tenant_code = tenant_code
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT, **_HEADERS})

    def close(self) -> None:
        self.session.close()

    def _get(self, path: str, params: dict) -> Optional[str]:
        resp = self.session.get(f"{self.base_url}/{path}", params=params, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_paths(self, operacion_raw: str, max_items: Optional[int] = None) -> Iterator[str]:
        position = 0
        count = 0
        seen = set()
        while True:
            html = self._get(
                "busca_prop.php",
                {
                    "tipo_operacion": operacion_raw,
                    "tipo_propiedad": "-",
                    "posicion_actual": position,
                    "co": self.tenant_code,
                },
            )
            if not html:
                break
            soup = BeautifulSoup(html, "lxml")
            paths = [a.get("href") for a in soup.select('a[href^="detalle-item.php?item_id="]') if a.get("href")]
            new_paths = [p for p in dict.fromkeys(paths) if p not in seen]
            if not new_paths:
                break
            for path in new_paths:
                seen.add(path)
                yield path
                count += 1
                if max_items is not None and count >= max_items:
                    return
            position += PAGE_SIZE
            time.sleep(self.delay)

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        operations = (
            ["Venta", "Alquiler", "Alquiler Temporal"]
            if operation == "all"
            else [k for k, v in _OPERATION_MAP.items() if v == operation]
        )
        seen_ids = set()
        for operacion_raw in operations:
            for path in self.iter_paths(operacion_raw, max_items=max_pages):
                item = self._scrape_detail(path)
                if item is None or item.source_id in seen_ids:
                    continue
                seen_ids.add(item.source_id)
                yield item
                time.sleep(self.delay)

    def _scrape_detail(self, path: str) -> Optional[PropertyItem]:
        url = f"{self.base_url}/{path}"
        html = self._get(path, {})
        if html is None:
            return None
        try:
            return self._normalize(path, url, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, url)
            return None

    def _normalize(self, path: str, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        id_match = re.search(r"item_id=(\d+)", path)
        if not id_match:
            return None
        source_id = id_match.group(1)

        # Ledesma's own install uses h3 for address/price/title/operation;
        # Cabrera and Franco (same backend, different frontend skin) use h2
        # for the same 4 fields in the same order.
        headers = soup.select("h3")[:4]
        if len(headers) < 4:
            headers = soup.select("h2")[:4]
        address = headers[0].get_text(strip=True) if len(headers) > 0 else None
        price_text = headers[1].get_text(strip=True) if len(headers) > 1 else ""
        title = headers[2].get_text(strip=True) if len(headers) > 2 else None
        operation_raw = headers[3].get_text(strip=True).lower() if len(headers) > 3 else ""
        operation = {"venta": "sale", "alquiler": "rent"}.get(operation_raw, "sale")
        if "temporari" in operation_raw or "temporal" in operation_raw:
            operation = "temporal"

        currency, price = _parse_price(price_text)

        # Same story for the description: Ledesma has a free-text
        # `div.top20`; the other skin's div.top20 hits are share buttons
        # ("Twittear") or a one-line summary — skip those, prefer the
        # longest real block of text.
        desc_candidates = [d.get_text("\n", strip=True) for d in soup.select("div.top20")]
        desc_candidates = [d for d in desc_candidates if d and d.lower() != "twittear"]
        description = max(desc_candidates, key=len) if desc_candidates else None

        expenses_price = expenses_currency = None
        mapped = {}
        for div in soup.select("div.largo"):
            text = div.get_text(" ", strip=True)
            if not text:
                continue
            if text.lower().startswith("expensas"):
                expenses_currency, expenses_price = _parse_price(text.split(":", 1)[-1])
                continue
            for pattern, dest_key in _FIELD_PATTERNS:
                m = pattern.search(text)
                if not m:
                    continue
                if dest_key in ("total_m2", "covered_m2"):
                    mapped.setdefault(dest_key, _to_float(m.group(1)))
                else:
                    mapped.setdefault(dest_key, int(m.group(1)))
                break

        if not mapped:
            # Cabrera/Franco-style skin: no div.largo at all — fields sit as
            # "Label: value" text inside whichever heading says "informacion
            # del inmueble" (accents vary by page encoding, so match loosely).
            info_heading = next(
                (h for h in soup.select("h2, h3") if "informaci" in h.get_text(strip=True).lower()), None
            )
            info_text = info_heading.find_parent("div").get_text(" ", strip=True) if info_heading else ""
            for pattern, dest_key in _LABELED_FIELD_PATTERNS:
                m = pattern.search(info_text)
                if not m:
                    continue
                if dest_key in ("total_m2", "covered_m2"):
                    mapped.setdefault(dest_key, _to_float(m.group(1)))
                else:
                    mapped.setdefault(dest_key, int(m.group(1)))
            exp_m = re.search(r"expensas:?\s*([\d.,]+)", info_text, re.IGNORECASE)
            if exp_m:
                expenses_price = _to_float(exp_m.group(1))

        photos = [
            img.get("data-flickity-lazyload")
            for img in soup.select("img.carousel-cell-image[data-flickity-lazyload]")
            if img.get("data-flickity-lazyload")
        ]

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            description=description,
            operation=operation,
            price=price,
            currency=currency,
            expenses_price=expenses_price,
            expenses_currency=expenses_currency,
            address=address,
            total_m2=mapped.get("total_m2"),
            covered_m2=mapped.get("covered_m2"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            total_rooms=mapped.get("total_rooms"),
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw={},
        )


def _parse_price(text: str):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.search(r"([A-Za-z$]+)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency_raw_lower = currency_raw.lower()
    if "u$d" in currency_raw_lower or "usd" in currency_raw_lower:
        currency = "USD"
    elif "$" in currency_raw:
        currency = "ARS"
    else:
        currency = currency_raw.upper()
    return currency, _to_float(number_raw)


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    number = value.strip()
    cleaned = number.replace(".", "").replace(",", ".") if "," in number else number.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None
