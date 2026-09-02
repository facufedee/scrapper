"""Older-template variant of the ArgenCasas platform (see scrapers/argencasas.py
for the newer one, found via Ferrero). Found via Inmobiliaria Rejn (Ituzaingó):
same backend (photo/CDN paths under `argencasas.com`), but a different,
older frontend template — different URLs, no `var_dump()` leftover, and
critically, robots.txt disallows `/motor/`, which is where this template's
pagination lives (`/motor/props.php?...&page=N`). So no deep pagination here.

Discovery instead uses the site's own sitemap.xml.gz, which lists many
narrow zone/type category pages (e.g. `/casas-venta-ituzaingo-norte`) rather
than a few broad ones — only page 1 of each is fetched (page 1 is the plain
category URL itself, never `/motor/`), which in practice covers the large
majority of listings given how finely the categories are already split.

Each detail page (`/propiedad-{slug}-{inmobId}-{propId}`) embeds a clean
schema.org RealEstateListing JSON-LD block (price, address, geo, rooms,
bedrooms, floorSize) — bathrooms and covered/land m² aren't in it, but are in
the plain-text `og:description` meta tag, so those are regex-parsed from
there instead.
"""

import gzip
import json
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

_DETAIL_HREF_RE = re.compile(r"/propiedad-[a-z0-9-]+-(\d+)-(\d+)(?=[\"'])")
_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}


class ArgenCasasLegacyScraper(BaseScraper):
    all_in_one = True

    def __init__(self, base_url: str, source_name: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def close(self) -> None:
        self.session.close()

    def _get(self, url: str) -> Optional[str]:
        resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_urls(self, max_items: Optional[int] = None) -> Iterator[str]:
        gz_resp = self.session.get(f"{self.base_url}/sitemap.xml.gz", timeout=config.REQUEST_TIMEOUT)
        gz_resp.raise_for_status()
        sitemap_xml = gzip.decompress(gz_resp.content).decode("utf-8")
        category_urls = re.findall(r"<loc>(.*?)</loc>", sitemap_xml)

        seen = set()
        count = 0
        for cat_url in category_urls:
            cat_url = cat_url.replace("http://", "https://")
            html = self._get(cat_url)
            if not html:
                continue
            for inmob_id, prop_id in _DETAIL_HREF_RE.findall(html):
                key = f"{inmob_id}-{prop_id}"
                if key in seen:
                    continue
                seen.add(key)
                match = re.search(rf'href="(/propiedad-[a-z0-9-]+-{inmob_id}-{prop_id})"', html)
                if not match:
                    continue
                yield f"{self.base_url}{match.group(1)}"
                count += 1
                if max_items is not None and count >= max_items:
                    return
            time.sleep(self.delay)

    def fetch_listings(
        self,
        operation: str = "all",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        for url in self.iter_urls(max_items=max_pages):
            item = self._scrape_detail(url)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, url: str) -> Optional[PropertyItem]:
        html = self._get(url)
        if html is None:
            return None
        try:
            return self._normalize(url, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, url)
            return None

    def _normalize(self, url: str, html: str) -> Optional[PropertyItem]:
        id_match = re.search(r"-(\d+)-(\d+)$", url.split("?")[0])
        if not id_match:
            return None
        source_id = f"{id_match.group(1)}-{id_match.group(2)}"

        soup = BeautifulSoup(html, "lxml")
        listing_ld = None
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                # strict=False: the site's own description text sometimes has
                # raw, unescaped newlines inside the JSON string value
                data = json.loads(script.get_text() or "", strict=False)
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get("@type") == "RealEstateListing":
                listing_ld = data
                break

        if not listing_ld:
            return None

        offer = listing_ld.get("offers") or {}
        entity = listing_ld.get("mainEntity") or {}
        address = entity.get("address") or {}
        geo = entity.get("geo") or {}
        floor_size = (entity.get("floorSize") or {}).get("value")

        og_desc_el = soup.select_one('meta[property="og:description"]')
        og_desc = og_desc_el.get("content") if og_desc_el else ""
        bathrooms = _search_int(og_desc, r"([\d.,]+)\s*ba[ñn]os?")
        covered_m2 = _search_float(og_desc, r"cubiert[ao]s?\s*([\d.,]+)\s*m2")
        land_m2 = _search_float(og_desc, r"libre\s*([\d.,]+)\s*m2")

        operation_raw = "venta" if "-venta-" in url else ("alquiler" if "-alquiler-" in url else "")
        operation = _OPERATION_MAP.get(operation_raw, "sale")

        # property_type from the URL slug ("/propiedad-casa-venta-..." -> "casa")
        # is more consistent/usable than additionalType's English producttology URL
        slug_type_match = re.search(r"/propiedad-([a-z]+)-", url)
        property_type = slug_type_match.group(1).capitalize() if slug_type_match else None

        seller = offer.get("seller") or {}

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=listing_ld.get("name"),
            description=listing_ld.get("description"),
            property_type=property_type,
            operation=operation,
            price=_to_float(offer.get("price")),
            currency=offer.get("priceCurrency"),
            address=address.get("streetAddress"),
            city=address.get("addressLocality"),
            province=address.get("addressRegion"),
            lat=_plain_float(geo.get("latitude")),
            lon=_plain_float(geo.get("longitude")),
            total_rooms=entity.get("numberOfRooms"),
            bedrooms=entity.get("numberOfBedrooms"),
            bathrooms=bathrooms,
            land_m2=land_m2,
            covered_m2=covered_m2,
            total_m2=_plain_float(floor_size),
            agent_name=seller.get("name") or self.source_name,
            agent_phone=seller.get("telephone"),
            office_name=seller.get("name") or self.source_name,
            photos=_extract_photos(html, self.base_url),
            raw=listing_ld,
        )


def _extract_photos(html: str, base_url: str) -> list:
    urls = re.findall(r"/fotos/\d+/\d+/\d+\.jpg", html)
    seen = []
    for u in urls:
        full = f"{base_url}{u}"
        if full not in seen:
            seen.append(full)
    return seen


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _plain_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _search_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", ".")))
    except ValueError:
        return None


def _search_float(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None
