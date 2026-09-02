"""Matías Szpira Bienes Raíces (Moreno/zona oeste) — Tokko-sourced data via
the site's own React frontend, proxied through a local JSON API.

The homepage's confirmed `static.tokkobroker.com` asset (the only signal
found on first pass) suggested Tokko, but the detail pages render as a
React SPA (`id="app"`) using a template completely different from the
server-rendered Tokko theme in scrapers/tokko.py — no HTML scraping needed
at all here, though: watching the page load in a real browser (Playwright)
showed it calling its own local endpoints:

  - `/api/results.json?page=N&tipo_operacion={V|A|T}` — paginated listing
    (15/page), operation is required explicitly; the response's schema
    (`resultado.fichas`/`resultado.datos.paginas`, `in_*` field prefixes)
    is the same Xintel-family shape seen in scrapers/xintel.py, just proxied
    locally instead of calling xintelapi.com.ar with a client-side key —
    the same pattern as scrapers/fparadela.py, but with different field
    names since this tenant's data actually originates from Tokko
    (`in_tokko_*` fields, `tokko_publication_id`).
  - `/api/property.json?suc=TKO&id={id}&amaira=false` — full detail per
    listing (description, lat/lon, full photo gallery, agent phone) —
    `results.json` alone only has a single thumbnail and no description.

No robots.txt restrictions (empty response). This is a much bigger catalog
than it first looked — ~1,170 properties, not the dozen visible on the
homepage.
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

BASE_URL = "https://matiasszpira.com.ar"
TENANT_CODE = "TKO"

_OPERATION_MAP = {"V": "sale", "A": "rent", "T": "temporal"}


class MatiasSzpiraScraper(BaseScraper):
    source_name = "matiasszpira"
    all_in_one = True  # loops all 3 operation codes itself when called with operation="all"

    def __init__(self, delay: Optional[float] = None):
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get_json(self, path: str, params: dict) -> Optional[dict]:
        resp = self.session.get(f"{BASE_URL}/{path}", params=params, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def iter_refs(self, op_code: str, max_items: Optional[int] = None) -> Iterator[tuple]:
        page = 1
        count = 0
        while True:
            data = self._get_json("api/results.json", {"page": page, "tipo_operacion": op_code})
            resultado = (data or {}).get("resultado") or {}
            fichas = resultado.get("fichas") or []
            if not fichas:
                break
            for f in fichas:
                yield f.get("codsuc") or TENANT_CODE, f.get("id")
                count += 1
                if max_items is not None and count >= max_items:
                    return
            paginas = int(resultado.get("datos", {}).get("paginas") or 1)
            if page >= paginas:
                break
            page += 1
            time.sleep(self.delay)

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        op_codes = ["V", "A", "T"] if operation == "all" else [
            code for code, mapped in _OPERATION_MAP.items() if mapped == operation
        ]
        seen_ids = set()
        for op_code in op_codes:
            for suc, prop_id in self.iter_refs(op_code, max_items=max_pages):
                if prop_id in seen_ids:
                    continue
                seen_ids.add(prop_id)
                item = self._scrape_detail(suc, prop_id)
                if item is None:
                    continue
                yield item
                time.sleep(self.delay)

    def _scrape_detail(self, suc: str, prop_id: str) -> Optional[PropertyItem]:
        try:
            data = self._get_json("api/property.json", {"suc": suc, "id": prop_id, "amaira": "false"})
        except Exception:
            logger.exception("Failed to fetch matiasszpira property %s", prop_id)
            return None
        resultado = (data or {}).get("resultado") or {}
        fichas = resultado.get("ficha") or []
        if not fichas:
            return None
        try:
            return self._normalize(fichas[0], resultado.get("img") or [])
        except Exception:
            logger.exception("Failed to parse matiasszpira property %s", prop_id)
            return None

    def _normalize(self, f: dict, photos: list) -> Optional[PropertyItem]:
        source_id = f.get("id")
        if not source_id:
            return None

        operation_raw = (f.get("in_ope") or "").strip().upper()
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        currency, price = _parse_price(f.get("precio"))

        return PropertyItem(
            source=self.source_name,
            source_id=str(source_id),
            url=f"{BASE_URL}/propiedad/{source_id}/",
            title=f.get("titulo") or f.get("tipo") or None,
            description=_clean_description(f.get("in_obs")),
            property_type=f.get("tipo") or None,
            operation=operation,
            price=price,
            currency=currency,
            address=f.get("direccion_completa") or None,
            neighborhood=f.get("in_bar") or None,
            city=f.get("in_loc") or None,
            lat=_to_float(f.get("latitud")),
            lon=_to_float(f.get("longitud")),
            total_rooms=_to_int(f.get("in_amb")),
            bedrooms=_to_int(f.get("ti_dor")),
            bathrooms=_to_int(f.get("in_bao")),
            total_m2=_to_float(f.get("in_sto")),
            covered_m2=_to_float(f.get("in_cub")),
            agent_phone=f.get("vendedor_celular") or f.get("whatsapp") or None,
            office_name=self.source_name,
            photos=[p for p in photos if p],
            raw={
                "tipo": f.get("tipo"),
                "in_ant": f.get("in_ant"),
                "in_dis": f.get("in_dis"),
                "in_ori": f.get("in_ori"),
                "in_tokko_region": f.get("in_tokko_region"),
            },
        )


def _parse_price(text: Optional[str]):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.match(r"([A-Za-z$]+)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if "usd" in currency_raw.lower() else ("ARS" if "$" in currency_raw else currency_raw.upper())
    return currency, _to_float(number_raw)


def _clean_description(html: Optional[str]) -> Optional[str]:
    if not html:
        return None
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip() or None


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _to_int(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None
