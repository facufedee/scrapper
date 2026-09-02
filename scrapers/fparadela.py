"""Fernando Paradela Inmuebles (Ituzaingó) — Amaira/Xintel via the site's own proxy.

The site's frontend calls its own `/api/proxy.php` (no client-exposed API
key, unlike the direct-`xintelapi.com.ar` pattern in scrapers/xintel.py) —
`GET fparadela.com.ar/api/proxy.php?page=N&per_page=20` returns full,
already-paginated JSON (`data`/`total`/`last_page`), no HTML rendering or
detail-page fetch needed at all. The listings themselves are branded
"Amaira" (`ficha.amaira.com.ar`) but the photo CDN (`cdn-images.xintelweb.com`)
shows this is the same underlying Xintel-family backend as Grupo Vaccaro/
Gabriel Paris, just fronted by this site's own proxy instead of a
client-side API key — kept as a standalone scraper since no other agency
using this exact `api/proxy.php` shape has turned up yet. No robots.txt
restrictions (the response is the site platform's generic Angular
404 shell, no real Disallow rules).
"""

import logging
import time
from typing import Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

BASE_URL = "https://fparadela.com.ar"
PER_PAGE = 20

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporario": "temporal"}
_CURRENCY_MAP = {"u$s": "USD", "usd": "USD", "ars": "ARS", "$": "ARS"}


class FParadelaScraper(BaseScraper):
    source_name = "fparadela"
    all_in_one = True  # proxy mixes all operations in one paginated feed

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get_page(self, page: int) -> Optional[dict]:
        resp = self.session.get(
            f"{BASE_URL}/api/proxy.php",
            params={"page": page, "per_page": PER_PAGE},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        page = 1
        last_page = None
        count = 0
        while last_page is None or page <= last_page:
            data = self._get_page(page)
            if not data:
                break
            last_page = data.get("last_page") or 1

            for raw in data.get("data") or []:
                try:
                    item = self._normalize(raw)
                except Exception:
                    logger.exception("Failed to parse fparadela item %s", raw.get("id"))
                    continue
                if item is None:
                    continue
                if operation != "all" and item.operation != operation:
                    continue
                yield item
                count += 1
                if max_pages is not None and count >= max_pages:
                    return

            page += 1
            time.sleep(self.delay)

    def _normalize(self, raw: dict) -> Optional[PropertyItem]:
        source_id = raw.get("id")
        if source_id is None:
            return None

        data = raw.get("data") or {}
        valores = raw.get("valores") or {}
        ubicacion = raw.get("ubicacion") or {}
        superficies = raw.get("superficies") or {}

        operation_raw = (data.get("operacion") or "").strip().lower()
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        if operation == "rent":
            price = _to_float(valores.get("alquiler"))
            currency = _CURRENCY_MAP.get((valores.get("moneda_alquiler_simbolo") or "").strip().lower())
        else:
            price = _to_float(valores.get("venta"))
            currency = _CURRENCY_MAP.get((valores.get("moneda_venta_simbolo") or "").strip().lower())
        if not valores.get("mostrar_precio", True):
            price = None

        lat = lon = None
        coo = ubicacion.get("coordenadas") or ""
        if "," in coo:
            lat_raw, lon_raw = coo.split(",", 1)
            lat = _to_float(lat_raw)
            lon = _to_float(lon_raw)

        amigable = (raw.get("amigable_url") or "").lstrip("/")
        url = f"{BASE_URL}/ficha.php?ficha={amigable}" if amigable else raw.get("amaira_url")

        ambientes = data.get("ambientes") or {}

        return PropertyItem(
            source=self.source_name,
            source_id=str(source_id),
            url=url,
            title=data.get("titulo") or None,
            description=raw.get("observaciones_plain_text") or None,
            property_type=data.get("tipologia") or None,
            operation=operation,
            price=price,
            currency=currency,
            address=ubicacion.get("direccion") or None,
            neighborhood=ubicacion.get("barrio") or None,
            city=ubicacion.get("localidad") or None,
            lat=lat,
            lon=lon,
            total_rooms=_to_int(ambientes.get("ambientes")),
            bedrooms=_to_int(ambientes.get("dormitorios")),
            bathrooms=_to_int(data.get("banios")),
            total_m2=_to_float(superficies.get("total")),
            covered_m2=_to_float(superficies.get("cubierta")),
            office_name=self.source_name,
            photos=[p for p in (raw.get("imagenes") or []) if p],
            raw={
                "tipologia": data.get("tipologia"),
                "estado_en_internet": data.get("estado_en_internet"),
                "banios": data.get("banios"),
                "cocheras": data.get("cocheras"),
                "antiguedad": data.get("antiguedad"),
            },
        )


def _to_float(value) -> Optional[float]:
    if value in (None, "", 0):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
