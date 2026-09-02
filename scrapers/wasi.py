"""Generic scraper for agency sites built on "Wasi" (wasi.co), a Latin
American real estate CRM/website SaaS. Found via Inmobiliaria Di Casoli
(Ituzaingó) and confirmed on Gonzalo Propiedades, Repetto Propiedades and
Lasala Propiedades — recognizable by `images.wasi.co` in the HTML.

Plain server-rendered HTML, no JS needed. Listing pages
(`/s/ventas?page=N`, `/s/alquileres?page=N`) link to detail pages at
`/{slug}/{id}`. Each detail page has a `RealEstateAgent`-adjacent JSON-LD
block (title/description/address/one photo/phone) plus a generic
`ul.list-li li` "Label: value" details block (same label-pattern-matching
approach as scrapers/houzez.py, since exact labels/wording could vary by
install) for price, m², rooms, bathrooms, property type.

No lat/lon and no full photo gallery found in the static HTML on the sites
checked so far (map and gallery both look JS/AJAX-loaded) — only the single
`og:image` is available without a browser.
"""

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

_FIELD_PATTERNS = [
    (re.compile(r"terreno"), "land_m2"),
    (re.compile(r"construida|cubiert"), "covered_m2"),
    (re.compile(r"^dormitorio"), "bedrooms"),
    (re.compile(r"^ba[ñn]o"), "bathrooms"),
    (re.compile(r"tipo de inmueble"), "property_type"),
    (re.compile(r"^ciudad"), "city"),
]


class WasiScraper(BaseScraper):
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
        count = 0
        for section in ("ventas", "alquileres"):
            page = 1
            seen = set()
            while True:
                html = self._get(f"{self.base_url}/s/{section}?page={page}")
                if not html:
                    break
                paths = re.findall(rf'href="({re.escape(self.base_url)}/[a-z0-9-]+/\d+)"', html)
                new_paths = [p for p in dict.fromkeys(paths) if p not in seen]
                if not new_paths:
                    break
                for url in new_paths:
                    seen.add(url)
                    yield url
                    count += 1
                    if max_items is not None and count >= max_items:
                        return
                if f"page={page + 1}" not in html:
                    break
                page += 1
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
        id_match = re.search(r"/(\d+)$", url)
        source_id = id_match.group(1) if id_match else None
        if not source_id:
            return None

        soup = BeautifulSoup(html, "lxml")

        ld = {}
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text() or "", strict=False)
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get("address") or data.get("numberOfRooms"):
                ld = data
                break

        title = ld.get("name")
        description = _strip_tags(ld.get("description"))
        address = ld.get("address")
        phone = ld.get("telephone")

        price_el = soup.select_one(".blq_precio .pr")
        price_label_el = soup.select_one(".blq_precio")
        price_label = price_label_el.get_text(" ", strip=True).lower() if price_label_el else ""
        operation = "rent" if "alquiler" in price_label else "sale"
        currency, price = _parse_price(price_el.get_text(strip=True) if price_el else "")

        fields = {}
        for li in soup.select("ul.list-li li"):
            strong = li.find("strong")
            if not strong:
                continue
            label = strong.get_text(strip=True).rstrip(":").lower()
            value = li.get_text(" ", strip=True).replace(strong.get_text(strip=True), "", 1).strip()
            fields[label] = value

        mapped = {}
        for label, value in fields.items():
            dest = next((d for pattern, d in _FIELD_PATTERNS if pattern.search(label)), None)
            if not dest or dest in mapped:
                continue
            if dest in ("land_m2", "covered_m2"):
                mapped[dest] = _to_float(value)
            elif dest in ("bedrooms", "bathrooms"):
                mapped[dest] = _first_int(value)
            else:
                mapped[dest] = value

        og_image = soup.select_one('meta[property="og:image"]')
        photos = [og_image.get("content")] if og_image and og_image.get("content") else []

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            description=description,
            property_type=mapped.get("property_type"),
            operation=operation,
            price=price,
            currency=currency,
            address=address,
            city=mapped.get("city"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            land_m2=mapped.get("land_m2"),
            covered_m2=mapped.get("covered_m2"),
            total_m2=mapped.get("covered_m2"),
            agent_phone=phone,
            agent_name=self.source_name,
            office_name=self.source_name,
            photos=photos,
            raw={"fields": fields, "ld": ld},
        )


def _parse_price(text: str):
    text = (text or "").strip()
    m = re.match(r"(US\$|AR\$|\$)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency = "USD" if m.group(1) == "US$" else "ARS"
    return currency, _to_float(m.group(2))


def _to_float(value: Optional[str]) -> Optional[float]:
    """Wasi installs mix number formats (seen: "US$800,000" — comma as
    thousands, American-style, not the Argentine dot-as-thousands used
    elsewhere) — so pick whichever of . or , appears last and check its
    trailing group length instead of assuming a fixed convention: 3 digits
    after it means it's a thousands separator, 1-2 means it's the decimal
    point, regardless of which character it is.
    """
    if not value:
        return None
    value = value.strip()
    m = re.match(r"(-?[\d.,]+)", value)
    if not m:
        return None
    number = m.group(1)
    last_sep = max(number.rfind("."), number.rfind(","))
    if last_sep == -1:
        cleaned = number
    else:
        trailing = number[last_sep + 1:]
        if len(trailing) == 3:
            cleaned = number.replace(".", "").replace(",", "")
        else:
            integer_part = number[:last_sep].replace(".", "").replace(",", "")
            cleaned = f"{integer_part}.{trailing}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _strip_tags(html: Optional[str]) -> Optional[str]:
    if not html:
        return None
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return text or None
