"""Generic adapter for the Xintel real estate CRM/SaaS (found via Grupo Vaccaro).

Unlike the other platforms here, Xintel's own frontend (grupovaccaro.com) is an
Angular SPA — curl gets the same empty shell for every route — but the site's
own JS calls a plain JSON API directly (`https://xintelapi.com.ar/`) with an
API key that's embedded client-side in the page source (the same key any
visitor's browser sends), so there's no need to render JS at all: one API
call returns full data for 10 properties at once (title, price, currency,
address, m², bedrooms, description, coordinates, photos), no per-listing
detail fetch required.

`json=resultados.fichas&inm={tenant_code}&apiK={api_key}&page=N` — each
response's `resultado.datos.paginas` gives the total page count, and
`resultado.fichas`/`resultado.img` are parallel same-order lists (fichas[i]'s
photos are img[i]). `xintelapi.com.ar/robots.txt` only has the newer
"content signals" opt-out format (no traditional Disallow rules), so nothing
blocks this.

`inm`/`apiK` are per-tenant — every new agency on this platform needs both
values pulled from that site's own page source (grep for `xintelapi.com.ar`
in a `$.ajax` block) before it can be added as a subclass.
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

API_URL = "https://xintelapi.com.ar/"

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}
_CURRENCY_MAP = {"u$s": "USD", "usd": "USD", "$": "ARS"}


class XintelScraper(BaseScraper):
    all_in_one = True

    def __init__(self, base_url: str, source_name: str, tenant_code: str, api_key: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.tenant_code = tenant_code
        self.api_key = api_key
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get_page(self, page: int) -> Optional[dict]:
        resp = self.session.get(
            API_URL,
            params={"json": "resultados.fichas", "inm": self.tenant_code, "apiK": self.api_key, "page": page},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("resultado")

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        page = 1
        total_pages = None
        count = 0
        while total_pages is None or page <= total_pages:
            result = self._get_page(page)
            if not result:
                break
            if total_pages is None:
                total_pages = int(result.get("datos", {}).get("paginas") or 1)

            fichas = result.get("fichas") or []
            imgs = result.get("img") or []
            for i, ficha in enumerate(fichas):
                photos = imgs[i] if i < len(imgs) else []
                try:
                    item = self._normalize(ficha, photos)
                except Exception:
                    logger.exception("Failed to parse %s ficha %s", self.source_name, ficha.get("in_num"))
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

    def _normalize(self, ficha: dict, photos: list) -> Optional[PropertyItem]:
        source_id = ficha.get("in_num")
        if not source_id:
            return None

        operation_raw = (ficha.get("operacion") or "").strip().lower()
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        if operation == "rent":
            price = _to_float(ficha.get("alquiler_precio"))
            currency = _CURRENCY_MAP.get((ficha.get("alquiler_moneda") or "").strip().lower())
        else:
            price = _to_float(ficha.get("venta_precio"))
            currency = _CURRENCY_MAP.get((ficha.get("venta_moneda") or "").strip().lower())

        lat = lon = None
        coo = ficha.get("in_coo") or ""
        if "," in coo:
            lat_raw, lon_raw = coo.split(",", 1)
            lat = _to_float(lat_raw)
            lon = _to_float(lon_raw)

        address = (ficha.get("direccion_completa") or "").strip() or None

        amigable = (ficha.get("amigable") or "").lstrip("/")
        url = f"{self.base_url}/{amigable}" if amigable else None

        total_m2 = _to_float(ficha.get("in_sup"))
        covered_m2 = _to_float(ficha.get("in_cub"))

        # curated subset only — the full `ficha` dict is a ~300-field CRM record
        # that includes salesperson PII (pe_dni, pe_mai, etc.) we have no
        # business persisting just because the site's own frontend receives it
        raw = {
            "tipo": ficha.get("tipo"),
            "estado": ficha.get("estado"),
            "ambientes_num": ficha.get("ambientes_num"),
            "dormitorios": ficha.get("dormitorios"),
            "in_sup": ficha.get("in_sup"),
            "in_cub": ficha.get("in_cub"),
            "in_bar": ficha.get("in_bar"),
            "in_loc": ficha.get("in_loc"),
            "amigable": ficha.get("amigable"),
        }

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=ficha.get("titulo") or None,
            description=ficha.get("in_obs") or None,
            property_type=ficha.get("tipo") or None,
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            neighborhood=ficha.get("in_bar") or None,
            city=ficha.get("in_loc") or None,
            lat=lat,
            lon=lon,
            total_rooms=_first_int(ficha.get("cantidad_ambientes")),
            bedrooms=_first_int(ficha.get("cantidad_dormitorios")),
            total_m2=total_m2 or None,
            covered_m2=covered_m2 or None,
            agent_phone=ficha.get("vendedor_celular") or ficha.get("vendedor_telefono") or None,
            office_name=self.source_name,
            photos=[p for p in photos if p],
            raw=raw,
        )


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _first_int(value) -> Optional[int]:
    if not value:
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None
