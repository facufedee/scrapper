"""Generic adapter for the Carlucci/Piccione shared platform (Ituzaingó agencies).

Server-rendered PHP/Laravel-ish site (CDN at d1v2p1s05qqabi.cloudfront.net,
"sites/{id}" path per tenant) — a shared multi-tenant platform, same idea as
scrapers/argencasas.py, scrapers/houzez.py, etc. No JS needed.

Listing (`/propiedades?page=N`) mixes both operations (venta+alquiler) in one
paginated list — no need to iterate operations separately. Each detail page
(`/propiedad/{slug}--{id}`) has a clean `ul.details li.{field}` structure:
`<li class="col-md-4 col-sm-6 area"><b>Sup. Total:</b> 284 m2</li>`, so the
li's own class name is already the field key.

robots.txt disallows `/property/markers` (their map data endpoint) and
`/whatsapp?` (click tracking) — neither is used here, so lat/lon isn't
available for this source and agent_phone comes from the general contact
widget, not a per-listing endpoint.
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

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

_DETAIL_LINK_RE = re.compile(r"/propiedad/[a-z0-9-]+--\d+")

_FIELD_MAP = {
    "area": "total_m2",
    "covered_area": "covered_m2",
    "ground_area": "land_m2",
    "bedrooms": "bedrooms",
    "bathrooms": "bathrooms",
    "type": "property_type",
}


class CarlucciPlatformScraper(BaseScraper):
    all_in_one = True  # /propiedades mixes venta+alquiler in one paginated list

    def __init__(self, base_url: str, source_name: str, delay: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = requests.Session()
        retry = Retry(total=config.MAX_RETRIES, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"User-Agent": config.USER_AGENT, **_HEADERS})

    def close(self) -> None:
        self.session.close()

    def _get(self, path: str) -> Optional[str]:
        resp = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=config.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def iter_paths(self, max_items: Optional[int] = None) -> Iterator[str]:
        page = 1
        count = 0
        seen = set()
        while True:
            html = self._get(f"propiedades?page={page}")
            if not html:
                break
            paths = _DETAIL_LINK_RE.findall(html)
            new_paths = [p for p in dict.fromkeys(paths) if p not in seen]
            if not new_paths:
                break
            for path in new_paths:
                seen.add(path)
                yield path
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
        for path in self.iter_paths(max_items=max_pages):
            item = self._scrape_detail(path)
            if item is None:
                continue
            if operation != "all" and item.operation != operation:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, path: str) -> Optional[PropertyItem]:
        url = f"{self.base_url}{path}"
        html = self._get(path)
        if html is None:
            return None
        try:
            return self._normalize(url, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, url)
            return None

    def _normalize(self, url: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        id_match = re.search(r"--(\d+)$", url)
        source_id = id_match.group(1) if id_match else None
        if not source_id:
            return None

        title_el = soup.find("h1")
        address_el = soup.select_one("p.subtitle")

        price_el = soup.select_one(".card-price .text-primary") or soup.find("span", class_="text-primary")
        currency, price = _parse_price(price_el.get_text(strip=True) if price_el else "")

        operation_match = re.search(r"Precio de (\w+)", html, re.IGNORECASE)
        operation_raw = operation_match.group(1).lower() if operation_match else ""
        operation = {"venta": "sale", "alquiler": "rent"}.get(operation_raw, "sale")

        desc_el = soup.select_one(".description p")
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        fields = {}
        for li in soup.select("ul.details li"):
            classes = li.get("class") or []
            key = classes[-1] if classes else None
            b_tag = li.find("b")
            if not key or not b_tag:
                continue
            label = b_tag.get_text(strip=True)
            value = li.get_text(" ", strip=True).replace(label, "", 1).strip()
            fields[key] = value

        photos = [img.get("src") for img in soup.select("img.rsImg") if img.get("src")]

        phone_match = re.search(r"wa\.me/\+?(\d+)", html)

        mapped = {}
        for src_key, dest_key in _FIELD_MAP.items():
            raw_value = fields.get(src_key)
            if raw_value is None:
                continue
            if dest_key in ("total_m2", "covered_m2", "land_m2"):
                mapped[dest_key] = _to_float(raw_value)
            elif dest_key in ("bedrooms", "bathrooms"):
                mapped[dest_key] = _first_int(raw_value)
            else:
                mapped[dest_key] = raw_value

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title_el.get_text(strip=True) if title_el else None,
            description=description,
            property_type=mapped.get("property_type"),
            operation=operation,
            price=price,
            currency=currency,
            address=address_el.get_text(strip=True) if address_el else None,
            total_m2=mapped.get("total_m2"),
            covered_m2=mapped.get("covered_m2"),
            land_m2=mapped.get("land_m2"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            agent_name=self.source_name,
            agent_phone=phone_match.group(1) if phone_match else None,
            office_name=self.source_name,
            photos=photos,
            raw=fields,
        )


def _parse_price(text: str):
    text = (text or "").strip()
    if not text:
        return None, None
    m = re.match(r"([A-Za-z$]+)\s*([\d.,]+)", text)
    if not m:
        return None, None
    currency_raw, number_raw = m.groups()
    currency = "USD" if "usd" in currency_raw.lower() else ("ARS" if "$" in currency_raw else currency_raw.upper())
    return currency, _to_float(number_raw)


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    # only the first number (e.g. "284" out of "284 m2" — the li's rendered
    # "m<sup>2</sup>" collapses to "284 m 2", and blindly stripping non-digits
    # would glue the "284" and the sup's "2" into "2842")
    m = re.match(r"\s*([\d.,]+)", value)
    if not m:
        return None
    number = m.group(1)
    cleaned = number.replace(".", "").replace(",", ".") if "," in number else number.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_int(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


class CarlucciScraper(CarlucciPlatformScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://icarlucci.com.ar", source_name="carlucci", delay=delay)
