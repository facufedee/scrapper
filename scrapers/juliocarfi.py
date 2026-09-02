"""Julio Carfí Propiedades (Castelar) — the other Carfi brother's agency.

Modern Vue SPA; the site itself renders nothing server-side, but its JS
bundle calls a plain public REST API at back.juliocarfi.com.ar (Laravel,
paginated, `Disallow:` empty in robots.txt) that returns full property
records directly — no HTML scraping at all. Found by pulling apart the
site's own JS bundle to find the API base URL and guessing the (very
RESTful) endpoint name, `/api/propiedades`.

By far the largest single-agency source found in this batch: ~6,500
properties across the whole website group (back.juliocarfi.com.ar seems to
serve more than just Castelar/zona oeste — filtering isn't applied here, so
this pulls everything the API returns; `province_id`/`localidad` are kept in
`raw` if it turns out worth restricting later).
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

API_BASE = "https://back.juliocarfi.com.ar/api"
FRONTEND_BASE = "https://juliocarfi.com.ar"


class JulioCarfiScraper(BaseScraper):
    source_name = "juliocarfi"
    all_in_one = True

    def __init__(self, page_size: int = 50, delay: Optional[float] = None):
        self.page_size = page_size
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})

    def close(self) -> None:
        self.session.close()

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        page = 1
        count = 0
        while True:
            resp = self.session.get(
                f"{API_BASE}/propiedades", params={"page": page, "per_page": self.page_size}, timeout=config.REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("data") or []
            if not items:
                break

            for raw in items:
                for prop_item in self._normalize(raw):
                    if operation != "all" and prop_item.operation != operation:
                        continue
                    yield prop_item
                    count += 1
                    if max_pages is not None and count >= max_pages:
                        return

            meta = payload.get("meta") or {}
            if page >= (meta.get("last_page") or page):
                break
            page += 1
            time.sleep(self.delay)

    def _normalize(self, raw: dict) -> Iterator[PropertyItem]:
        """A listing can be offered for sale and/or rent at once (separate
        valor/valor_alquiler) — yield one PropertyItem per operation actually
        priced, sharing the same underlying listing id with an operation
        suffix so both can coexist under the (source, source_id) unique key."""
        try:
            prop_id = raw.get("id")
            if not prop_id:
                return

            attrs = {a["nombre"].strip().lower(): a["valor"] for a in (raw.get("atributos") or []) if a.get("nombre")}
            categorias = raw.get("categorias") or []
            property_type = categorias[0]["descripcion"] if categorias else None

            localidad = (raw.get("localidad") or {}).get("descripcion")
            barrio = (raw.get("barrio") or {}).get("descripcion") if raw.get("barrio") else None

            contacto = raw.get("contacto") or {}
            agent_name = " ".join(filter(None, [contacto.get("nombre"), contacto.get("apellido")])).strip() or None

            photos = [img["url"] for img in (raw.get("imagenes") or []) if img.get("url")]

            common = dict(
                title=f"{property_type or ''} en {localidad or ''}".strip(" -") or raw.get("direccion"),
                description=raw.get("descripcion"),
                property_type=property_type,
                address=raw.get("direccion"),
                neighborhood=barrio,
                city=localidad,
                lat=_to_float(raw.get("latitud")),
                lon=_to_float(raw.get("longitud")),
                total_rooms=_to_int(attrs.get("ambientes")),
                bedrooms=_to_int(attrs.get("dormitorios")),
                bathrooms=_to_int(attrs.get("baños") or attrs.get("banos")),
                total_m2=_to_float(attrs.get("metros totales")),
                covered_m2=_to_float(attrs.get("metros cubiertos")),
                agent_name=agent_name,
                agent_phone=contacto.get("telefono"),
                agent_email=contacto.get("email"),
                office_name=self.source_name,
                photos=photos,
                raw=raw,
            )

            sale_price = _to_float(raw.get("valor"))
            if sale_price:
                yield PropertyItem(
                    source=self.source_name,
                    source_id=f"{prop_id}-venta",
                    url=f"{FRONTEND_BASE}/propiedad/{prop_id}",
                    operation="sale",
                    price=sale_price,
                    currency=raw.get("moneda"),
                    **common,
                )

            rent_price = _to_float(raw.get("valor_alquiler"))
            if rent_price:
                yield PropertyItem(
                    source=self.source_name,
                    source_id=f"{prop_id}-alquiler",
                    url=f"{FRONTEND_BASE}/propiedad/{prop_id}",
                    operation="rent",
                    price=rent_price,
                    currency=raw.get("moneda_alquiler"),
                    **common,
                )

            if not sale_price and not rent_price:
                # no price on either operation — still worth keeping, default to sale
                yield PropertyItem(
                    source=self.source_name,
                    source_id=f"{prop_id}-venta",
                    url=f"{FRONTEND_BASE}/propiedad/{prop_id}",
                    operation="sale",
                    price=None,
                    currency=None,
                    **common,
                )
        except Exception:
            logger.exception("Failed to normalize Julio Carfi listing %s", raw.get("id"))
            return


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
