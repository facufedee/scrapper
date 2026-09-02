"""More Propiedades (Parque Leloir, Ituzaingó) — Xintel, direct API calls.

Same backend family as scrapers/xintel.py (Grupo Vaccaro/Gabriel Paris) —
confirmed via `cdn-images.xintelweb.com` photos and a visible client-side
`inm=REP`/`apiK=...` pair — but this tenant's frontend calls a *different*
Xintel JSON action per listing (`json=fichas.propiedades&suc=REP&id={id}`,
one ficha per call) instead of the paginated `resultados.fichas` action
scrapers/xintel.py uses, and the response schema differs just enough
(`cantidad_ambientes`/`cantidad_dormitorios` present, but price only as a
combined `precio` string rather than split `venta_precio`/`venta_moneda`)
that it isn't worth forcing through that shared class — kept standalone.

Discovery still uses this site's own server-rendered listing pages
(`propiedades.php?p=N&ope={v|a|t}`, no client-side rendering) rather than
the API's own listing endpoint, since the site's own list pages already
carry every id we need and needed no reverse-engineering — the *detail*
page is the one that renders "-" placeholders and only fills in the price
via JS, which is why the API is used per-item. No robots.txt restrictions
(404).
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

BASE_URL = "https://more-leloir.com"
API_URL = "https://xintelapi.com.ar/"
TENANT_CODE = "REP"
API_KEY = "4m17zq256jvsm24wOnqbev43y"

_OPERATION_TO_QS = {"sale": "v", "rent": "a", "temporal": "t"}
_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporario": "temporal"}
_ID_RE = re.compile(r"ficha-rep(\d+)")


class MoreLeloirScraper(BaseScraper):
    source_name = "moreleloir"

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get_html(self, path: str) -> Optional[str]:
        resp = self.session.get(f"{BASE_URL}/{path.lstrip('/')}", timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_ids(self, ope_qs: str, max_items: Optional[int] = None) -> Iterator[str]:
        page = 0
        count = 0
        seen = set()
        while True:
            html = self._get_html(f"propiedades.php?p={page}&ope={ope_qs}")
            if not html:
                break
            ids = _ID_RE.findall(html)
            new_ids = [i for i in dict.fromkeys(ids) if i not in seen]
            if not new_ids:
                break
            for prop_id in new_ids:
                seen.add(prop_id)
                yield prop_id
                count += 1
                if max_items is not None and count >= max_items:
                    return
            page += 1
            time.sleep(self.delay)

    def fetch_listings(
        self,
        operation: str = "sale",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        ope_qs = _OPERATION_TO_QS.get(operation)
        if ope_qs is None:
            return
        for prop_id in self.iter_ids(ope_qs, max_items=max_pages):
            item = self._scrape_detail(prop_id)
            if item is None:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, prop_id: str) -> Optional[PropertyItem]:
        try:
            resp = self.session.get(
                API_URL,
                params={
                    "json": "fichas.propiedades",
                    "amaira": "false",
                    "suc": TENANT_CODE,
                    "apiK": API_KEY,
                    "id": prop_id,
                },
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Failed to fetch moreleloir property %s", prop_id)
            return None

        resultado = (data or {}).get("resultado") or {}
        fichas = resultado.get("ficha")
        if not fichas:
            return None
        ficha = fichas[0] if isinstance(fichas, list) else fichas
        img = resultado.get("img") or []
        try:
            return self._normalize(ficha, img)
        except Exception:
            logger.exception("Failed to parse moreleloir property %s", prop_id)
            return None

    def _normalize(self, f: dict, photos: list) -> Optional[PropertyItem]:
        amigable = (f.get("amigable") or "").lstrip("-")
        if not amigable:
            return None
        id_match = re.search(r"ficha-rep(\d+)$", amigable)
        source_id = id_match.group(1) if id_match else amigable

        operation_raw = (f.get("operacion") or "").strip().lower()
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        currency, price = _parse_price(f.get("precio"))

        lat = lon = None
        coo = f.get("in_coo") or ""
        if "," in coo:
            lat_raw, lon_raw = coo.split(",", 1)
            lat = _plain_float(lat_raw)
            lon = _plain_float(lon_raw)
            if lat == 0 and lon == 0:
                lat = lon = None

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=f"{BASE_URL}/{amigable}",
            title=f.get("titulo") or None,
            operation=operation,
            price=price,
            currency=currency,
            address=f.get("direccion") or None,
            neighborhood=f.get("in_bar") or None,
            city=_strip_entities(f.get("in_loc")),
            lat=lat,
            lon=lon,
            total_rooms=_to_int(f.get("cantidad_ambientes")),
            bedrooms=_to_int(f.get("cantidad_dormitorios")),
            total_m2=_plain_float(f.get("in_sto")),
            covered_m2=_plain_float(f.get("in_cub")),
            agent_phone=f.get("vendedor_celular") or None,
            office_name=self.source_name,
            photos=[p for p in photos if p],
            raw={
                "estado": f.get("estado"),
                "in_bar": f.get("in_bar"),
                "in_loc": f.get("in_loc"),
            },
        )


def _strip_entities(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    import html as html_module
    return html_module.unescape(text)


def _parse_price(text: Optional[str]):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.match(r"([A-Za-z$]+)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency_raw_lower = currency_raw.lower()
    if "u$s" in currency_raw_lower or "usd" in currency_raw_lower:
        currency = "USD"
    elif "$" in currency_raw:
        currency = "ARS"
    else:
        currency = currency_raw.upper()
    return currency, _to_float(number_raw)


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    cleaned = text.replace(".", "").replace(",", ".") if "," in text else text.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _plain_float(value) -> Optional[float]:
    # unlike the Argentine-formatted display text `precio` uses, in_sto/in_cub/
    # in_coo come straight from the API as plain decimal strings ("600.00",
    # "-34.6241854") — the dot is always a decimal point here, never a
    # thousands separator, so no reformatting.
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _to_int(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None
