"""Generic scraper for agency sites built on the "RealHomes" WordPress real
estate theme (wpcasa.com) — another very common choice, alongside Houzez.
Found via Delizia Propiedades and Corigliano Propiedades (both Ituzaingó):
recognizable by `wp-content/plugins/realhomes-elementor-addon` and/or
`easy-real-estate` in the page source.

Unlike Houzez, nothing needs to be scraped from rendered HTML at all: the
theme registers a `property` custom post type (REST slug `propiedad` in the
installs seen so far, but that's a per-site translation/setting — discovered
dynamically via `/wp-json/wp/v2/types`) on WordPress's own public REST API,
with all the useful fields (price, m², bedrooms, bathrooms, lat/lng,
address, full photo set) in a `property_meta` object using the theme's
standard `REAL_HOMES_property_*` key names. `_embed=wp:term` resolves the
type/city/status taxonomy terms inline in the same request — no separate
lookups needed.
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

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}


class RealHomesScraper(BaseScraper):
    all_in_one = True

    def __init__(self, base_url: str, source_name: str, page_size: int = 50, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.page_size = page_size
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        self._rest_base = None  # resolved lazily: the CPT's REST slug varies per install

    def close(self) -> None:
        self.session.close()

    def _resolve_rest_base(self) -> str:
        if self._rest_base:
            return self._rest_base
        resp = self.session.get(f"{self.base_url}/wp-json/wp/v2/types", timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        types = resp.json()
        property_type = types.get("property")
        if not property_type:
            raise RuntimeError(f"{self.base_url}: no 'property' post type registered — not RealHomes?")
        self._rest_base = property_type["rest_base"]
        return self._rest_base

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        rest_base = self._resolve_rest_base()
        page = 1
        count = 0
        while True:
            resp = self.session.get(
                f"{self.base_url}/wp-json/wp/v2/{rest_base}",
                params={"page": page, "per_page": self.page_size, "_embed": "wp:term"},
                timeout=config.REQUEST_TIMEOUT,
            )
            if resp.status_code == 400:  # WP returns 400 "invalid page number" past the last page
                break
            resp.raise_for_status()
            items = resp.json()
            if not items:
                break

            for raw in items:
                item = self._normalize(raw)
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
        try:
            meta = raw.get("property_meta") or {}
            terms = [t for group in (raw.get("_embedded") or {}).get("wp:term", []) for t in group]

            def terms_for(taxonomy: str) -> list:
                return [t["name"] for t in terms if t.get("taxonomy") == taxonomy]

            property_type = next(iter(terms_for("property-type")), None)
            city = next(iter(terms_for("property-city")), None)
            status_terms = terms_for("property-status")
            operation_raw = (status_terms[0].lower() if status_terms else "")
            operation = _OPERATION_MAP.get(operation_raw, "sale")

            currency_raw = (meta.get("REAL_HOMES_property_price_prefix") or "").strip().upper()
            currency = "USD" if currency_raw in ("U$D", "USD", "U$S") else ("ARS" if currency_raw in ("$", "AR$") else currency_raw or None)
            price = _to_float(meta.get("REAL_HOMES_property_price"))

            loc = meta.get("REAL_HOMES_property_location") or {}
            lat = _to_float(loc.get("latitude"))
            lon = _to_float(loc.get("longitude"))

            images = meta.get("REAL_HOMES_property_images") or []
            photos = []
            for img in images:
                sizes = img.get("sizes") or {}
                url = (sizes.get("large") or {}).get("url") or (sizes.get("medium") or {}).get("url")
                if url:
                    photos.append(url)

            title = (raw.get("title") or {}).get("rendered")
            description = _strip_tags((raw.get("content") or {}).get("rendered"))

            return PropertyItem(
                source=self.source_name,
                source_id=str(raw["id"]),
                url=raw.get("link"),
                title=title,
                description=description,
                property_type=property_type,
                operation=operation,
                price=price,
                currency=currency,
                address=meta.get("REAL_HOMES_property_address"),
                city=city,
                lat=lat,
                lon=lon,
                bedrooms=_to_int(meta.get("REAL_HOMES_property_bedrooms")),
                bathrooms=_to_int(meta.get("REAL_HOMES_property_bathrooms")),
                land_m2=_to_float(meta.get("REAL_HOMES_property_lot_size")),
                covered_m2=_to_float(meta.get("REAL_HOMES_property_size")),
                total_m2=_to_float(meta.get("REAL_HOMES_property_size")),
                agent_name=self.source_name,
                office_name=self.source_name,
                photos=photos,
                raw=meta,
            )
        except Exception:
            logger.exception("Failed to normalize %s listing %s", self.source_name, raw.get("id"))
            return None


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    f = _to_float(value)
    return int(f) if f is not None else None


def _strip_tags(html: Optional[str]) -> Optional[str]:
    if not html:
        return None
    import re

    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return text or None
