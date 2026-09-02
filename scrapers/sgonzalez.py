"""Santiago González Inmobiliaria (zona oeste) — bespoke PHP catalog.

Fully server-rendered (`<title>` stays the generic site title on every
page, which made it *look* like a client-rendered SPA on first pass — the
actual content, including price/m²/description, is plain HTML). Listing
(`propiedades.php?operacion={Venta|Alquiler}`) has no pagination controls
at all — the whole result set renders on one page — so discovery is a
single fetch per operation, no page-loop needed. Detail pages
(`propiedad.php?id={code}`) have a clean per-field `<li>`/`<div>` class
structure (`li.sup`, `li.supCubierta`, `li.dormitorio`, `li.banio`,
`div.precio`). No robots.txt restrictions (404).
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

BASE_URL = "https://sgonzalez.com.ar"

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

_DETAIL_LINK_RE = re.compile(r"propiedad\.php\?id=[0-9/]+")

_OPERATION_TO_QS = {"sale": "Venta", "rent": "Alquiler"}


class SGonzalezScraper(BaseScraper):
    source_name = "sgonzalez"

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

    def fetch_listings(
        self,
        operation: str = "sale",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        operacion_qs = _OPERATION_TO_QS.get(operation)
        if operacion_qs is None:
            return
        html = self._get(f"propiedades.php?operacion={operacion_qs}")
        if not html:
            return
        paths = list(dict.fromkeys(_DETAIL_LINK_RE.findall(html)))
        if max_pages is not None:
            paths = paths[:max_pages]
        for path in paths:
            item = self._scrape_detail(path, operation)
            if item is None:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, path: str, operation: str) -> Optional[PropertyItem]:
        url = f"{BASE_URL}/{path}"
        html = self._get(path)
        if html is None:
            return None
        try:
            return self._normalize(path, url, operation, html)
        except Exception:
            logger.exception("Failed to parse sgonzalez listing %s", url)
            return None

    def _normalize(self, path: str, url: str, operation: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        id_match = re.search(r"id=([0-9/]+)", path)
        if not id_match:
            return None
        source_id = id_match.group(1)

        title_el = soup.select_one("#resultado h1")
        title = title_el.get_text(strip=True) if title_el else None

        tipo_items = [li.get_text(strip=True) for li in soup.select("ul.tipo li")]
        property_type = tipo_items[1] if len(tipo_items) > 1 else None

        address_el = soup.select_one(".dirección, .direccion")
        address = address_el.get_text(strip=True) if address_el else None

        fields = {}
        for li in soup.select("ul.descripcion li"):
            cls = li.get("class") or [None]
            fields[cls[0]] = li.get_text(strip=True)

        price_el = soup.select_one("div.precio")
        currency, price = _parse_price(price_el.get_text(strip=True) if price_el else "")

        desc_el = soup.select_one("p.descript")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        photos = [
            f"{BASE_URL}/{img.get('src').lstrip('/')}"
            for img in soup.select(".carousel-inner .carousel-item img[src]")
            if img.get("src")
        ]

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            description=description,
            property_type=property_type,
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            total_m2=_to_float(fields.get("sup")),
            covered_m2=_to_float(fields.get("supCubierta")),
            bedrooms=_first_int(fields.get("dormitorio")),
            bathrooms=_first_int(fields.get("banio")),
            office_name=self.source_name,
            photos=photos,
            raw=fields,
        )


def _parse_price(text: str):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.match(r"([A-Za-z$]+)\s*(\d[\d.,]*)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if "usd" in currency_raw.lower() or "u$s" in currency_raw.lower() else (
        "ARS" if "$" in currency_raw else currency_raw.upper()
    )
    return currency, _to_float(number_raw)


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = re.search(r"(\d[\d.,]*)", value)
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
