"""Pedro Lacoste Estudio Inmobiliario (Castelar).

Own small custom PHP site, but a very easy one: the listing page calls a
plain JSON API (`getPropiedades.php?offset=N`, 12 per page) that returns the
full property record directly — price, address, lat/lng, description, a
photo — no HTML scraping needed at all.
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

BASE_URL = "https://www.pedrolacoste.com.ar"
PAGE_SIZE = 12
_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}


class LacosteScraper(BaseScraper):
    source_name = "lacoste"
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
        offset = 0
        count = 0
        while True:
            resp = self.session.get(f"{BASE_URL}/getPropiedades.php", params={"offset": offset}, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            props = data.get("propiedades") or []
            if not props:
                break

            for raw in props:
                item = self._normalize(raw)
                if item is None:
                    continue
                if operation != "all" and item.operation != operation:
                    continue
                yield item
                count += 1
                if max_pages is not None and count >= max_pages:
                    return

            offset += PAGE_SIZE
            time.sleep(self.delay)

    def _normalize(self, raw: dict) -> Optional[PropertyItem]:
        try:
            prop_id = raw.get("IdPropiedad")
            if not prop_id:
                return None

            operation_raw = (raw.get("tipoOperacionDesc") or "").strip().lower()
            operation = _OPERATION_MAP.get(operation_raw, "sale")

            currency_raw = (raw.get("tipoImporteDesc") or "").strip().upper()
            currency = "USD" if currency_raw in ("U$S", "USD") else ("ARS" if currency_raw else None)
            price = _to_float(raw.get("propiedadImporte"))

            lat = lon = None
            latlng = raw.get("propiedadLatLng")
            if latlng and "," in latlng:
                lat_str, lon_str = latlng.split(",", 1)
                lat, lon = _to_float(lat_str), _to_float(lon_str)

            total_m2 = _to_float(raw.get("propiedadMetrosTotal")) or None
            covered_m2 = _to_float(raw.get("propiedadMetrosCubiertos")) or None

            photo_link = raw.get("propiedadLink")
            photos = [f"{BASE_URL}/{photo_link}"] if photo_link else []

            return PropertyItem(
                source=self.source_name,
                source_id=str(prop_id),
                url=f"{BASE_URL}/detalle_propiedad.php?id={prop_id}",
                title=f"{raw.get('tipoInmuebleDesc') or ''} en {operation_raw} - {raw.get('propiedadDireccion') or ''}".strip(" -"),
                description=raw.get("propiedadDescripcion"),
                property_type=raw.get("tipoInmuebleDesc"),
                operation=operation,
                price=price,
                currency=currency,
                address=raw.get("propiedadDireccion"),
                neighborhood=raw.get("BarrioDesc") or None,
                city=raw.get("LocalidadDesc") or None,
                lat=lat,
                lon=lon,
                bedrooms=_to_int(raw.get("propiedadCantDormi")),
                total_m2=total_m2,
                covered_m2=covered_m2,
                agent_name=self.source_name,
                office_name=self.source_name,
                photos=photos,
                raw=raw,
            )
        except Exception:
            logger.exception("Failed to normalize Lacoste listing %s", raw.get("IdPropiedad"))
            return None


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    f = _to_float(value)
    return int(f) if f is not None else None
