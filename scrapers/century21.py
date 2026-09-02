"""Generic adapter for Century21 Argentina's national portal
(century21.com.ar), scoped to one franchise office at a time.

Found via C21 La Moisse Lorré (Ituzaingó) — the office's own domain
(c21lamoisselorre.com.ar) just redirects to a page on the shared national
portal, which is a much bigger platform than any single agency's own site
(111 franchise offices across Argentina). Kept scoped per-office rather
than portal-wide since only zona oeste offices are in scope here.

Every page on the portal has a `?json=true` variant that returns the exact
data backing the rendered page — found by watching Playwright's network
tab, not documented anywhere:

  - Listing: `/v/resultados/[pagina_N/]oficina_{officeSlug}_local?json=true`
    — page 1 has no `pagina_N/` prefix, `pagina_2/`, `pagina_3/`, etc. for
    the rest; 100 results/page, `totalHits` gives the real total. The
    `officeSlug` (e.g. `94-lamoisse-lorre`) is shorter than the office's
    own `/v/oficina/{...}` path slug — no documented way to derive one
    from the other, so it's just a manually-confirmed constant per office.
  - Detail: `{urlCorrectaPropiedad from the listing}?json=true` — the
    listing already carries price/currency/m²/rooms/address/coordinates,
    but not the full description or photo gallery, so each item still
    needs one detail fetch (`entity.descripcion` for the description,
    top-level `fotos[].large` for photos).

robots.txt disallows `/busqueda`, `/ft/`, `/ds/`, `/pdf/` and a few other
paths — none of which this adapter touches (`/v/resultados/` and
`/propiedad/` aren't listed).
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

BASE_URL = "https://century21.com.ar"

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}


class Century21Scraper(BaseScraper):
    all_in_one = True  # listing mixes venta+alquiler in one paginated feed

    def __init__(self, office_slug: str, source_name: str, delay: Optional[float] = None):
        self.office_slug = office_slug
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get_json(self, path: str) -> Optional[dict]:
        resp = self.session.get(f"{BASE_URL}/{path.lstrip('/')}", params={"json": "true"}, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def iter_results(self, max_items: Optional[int] = None) -> Iterator[dict]:
        page = 1
        count = 0
        seen = set()
        while True:
            path = (
                f"v/resultados/oficina_{self.office_slug}_local" if page == 1
                else f"v/resultados/pagina_{page}/oficina_{self.office_slug}_local"
            )
            data = self._get_json(path)
            results = (data or {}).get("results") or []
            new_results = [r for r in results if r.get("id") not in seen]
            if not new_results:
                break
            for r in new_results:
                seen.add(r.get("id"))
                yield r
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
        for r in self.iter_results(max_items=max_pages):
            try:
                item = self._build_item(r)
            except Exception:
                logger.exception("Failed to parse century21 (%s) listing %s", self.source_name, r.get("id"))
                continue
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _build_item(self, r: dict) -> Optional[PropertyItem]:
        source_id = r.get("id")
        if not source_id:
            return None

        url_path = r.get("urlCorrectaPropiedad") or ""
        url = f"{BASE_URL}{url_path}" if url_path else None

        description = None
        photos = []
        if url_path:
            try:
                detail = self._get_json(url_path.lstrip("/"))
            except Exception:
                detail = None
            if detail:
                entity = detail.get("entity") or {}
                description = entity.get("descripcion") or None
                photos = [f.get("large") for f in (detail.get("fotos") or []) if f.get("large")]

        operation = _OPERATION_MAP.get((r.get("tipoOperacionTrans") or "").strip().lower(), "sale")

        precio_vista = (r.get("precios") or {}).get("vista") or {}
        currency = precio_vista.get("moneda") or None
        price = _to_float(precio_vista.get("precio"))

        neighborhood = r.get("colonia") or None
        city = r.get("municipio") or None
        address = r.get("calle") or None

        return PropertyItem(
            source=self.source_name,
            source_id=str(source_id),
            url=url,
            title=r.get("encabezado") or None,
            description=description,
            property_type=r.get("tipoPropiedadTrans") or None,
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            neighborhood=neighborhood,
            city=city,
            lat=_to_float(r.get("lat")),
            lon=_to_float(r.get("lon")),
            bedrooms=_to_int(r.get("recamaras")),
            bathrooms=_to_int(r.get("banos")),
            total_m2=_to_float(r.get("m2T")),
            covered_m2=_to_float(r.get("m2C")),
            agent_name=r.get("asesorNombre") or None,
            agent_phone=r.get("telefonoAfiliado") or r.get("telefono") or None,
            office_name=self.source_name,
            photos=photos,
            raw={
                "tipoPropiedad": r.get("tipoPropiedad"),
                "estado": r.get("estado"),
                "estacionamientos": r.get("estacionamientos"),
            },
        )


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
