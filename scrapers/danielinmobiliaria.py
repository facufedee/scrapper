"""Generic adapter for a bespoke ArgenCasas frontend template, confirmed on
Daniel Inmobiliaria and Zopatti Propiedades — same web dev shop, presumably,
building custom sites on top of the shared ArgenCasas backend (photos on
`api.argencasas.com`, same fingerprint as scrapers/argencasas.py /
argencasas_legacy.py) rather than either of ArgenCasas' own themes.

Listing (`/{venta|alquiler}/propiedades/pag-N`, infinite-scroll on the live
site but plain paginated HTML underneath) uses single-quoted `href='...'`
attributes, unlike every other source here — a `href="..."` grep silently
finds nothing, which is what made these look catalog-less at first. Detail
pages (`/ficha/{id}`) have a clean `ul.feat-label`-per-`<li>` structure
across two feature lists (`ficha-main-features` for m²/ambientes/
dormitorios/baños/cochera, `ficha-features` for everything else) and a
`Descripción` `<h2>` immediately followed by the description `<p>`.
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

_DETAIL_LINK_RE = re.compile(r"/ficha/[0-9-]+")

_FIELD_PATTERNS = [
    (re.compile(r"sup\s*total"), "total_m2"),
    (re.compile(r"sup\s*cubierta"), "covered_m2"),
    (re.compile(r"^ambientes"), "total_rooms"),
    (re.compile(r"^dormitorios"), "bedrooms"),
    (re.compile(r"^ba[ñn]os"), "bathrooms"),
]


class ArgenCasasCustomScraper(BaseScraper):
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

    def iter_paths(self, section: str, max_items: Optional[int] = None) -> Iterator[str]:
        page = 1
        count = 0
        seen = set()
        while True:
            path = f"{section}/propiedades" if page == 1 else f"{section}/propiedades/pag-{page}"
            html = self._get(path)
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
            page += 1
            time.sleep(self.delay)

    def fetch_listings(
        self,
        operation: str = "sale",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        section = {"sale": "venta", "rent": "alquiler"}.get(operation)
        if section is None:
            return
        for path in self.iter_paths(section, max_items=max_pages):
            item = self._scrape_detail(path, operation)
            if item is None:
                continue
            yield item
            time.sleep(self.delay)

    def _scrape_detail(self, path: str, operation: str) -> Optional[PropertyItem]:
        url = f"{self.base_url}{path}"
        html = self._get(path)
        if html is None:
            return None
        try:
            return self._normalize(path, url, operation, html)
        except Exception:
            logger.exception("Failed to parse %s listing %s", self.source_name, url)
            return None

    def _normalize(self, path: str, url: str, operation: str, html: str) -> Optional[PropertyItem]:
        soup = BeautifulSoup(html, "lxml")

        source_id = path.strip("/").split("/")[-1]
        if not source_id:
            return None

        h1 = soup.select_one(".ficha-heading h1")
        volanta = h1.select_one(".volanta").get_text(strip=True) if h1 and h1.select_one(".volanta") else None
        city = h1.select_one(".city").get_text(strip=True) if h1 and h1.select_one(".city") else None
        street_address = h1.select_one(".address").get_text(strip=True) if h1 and h1.select_one(".address") else None
        title = " - ".join(p for p in (volanta, city) if p) or None

        price_el = soup.select_one(".price")
        currency = amount = None
        if price_el:
            currency_el = price_el.select_one(".currency")
            amount_el = price_el.select_one(".amount")
            currency = currency_el.get_text(strip=True) if currency_el else None
            amount = _to_float(amount_el.get_text(strip=True)) if amount_el else None
        if currency:
            currency = "USD" if "usd" in currency.lower() else ("ARS" if "$" in currency else currency.upper())

        desc_el = None
        for h2 in soup.select(".block h2"):
            if "descripci" in h2.get_text(strip=True).lower():
                desc_el = h2.find_next_sibling("p")
                break
        description = desc_el.get_text("\n", strip=True) if desc_el else None

        fields = {}
        for li in soup.select("ul.ficha-main-features li, ul.ficha-features li"):
            label_el = li.select_one(".feat-label span")
            feat_label = li.select_one(".feat-label")
            if not label_el or not feat_label:
                continue
            label = label_el.get_text(strip=True)
            value = feat_label.get_text(" ", strip=True).replace(label, "", 1).strip()
            if label and value:
                fields[label] = value

        mapped = {}
        for label, value in fields.items():
            label_lower = label.lower()
            for pattern, dest_key in _FIELD_PATTERNS:
                if pattern.search(label_lower):
                    if dest_key in ("total_m2", "covered_m2"):
                        mapped[dest_key] = _to_float(value)
                    else:
                        mapped[dest_key] = _first_int(value)
                    break

        photos = [
            a.get("data-remote-src") for a in soup.select("#gallery a[data-remote-src]")
            if a.get("data-remote-src")
        ]
        photos = [f"https:{p}" if p.startswith("//") else p for p in photos]

        phone_match = re.search(r"tel:(\d+)", html)

        return PropertyItem(
            source=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            description=description,
            operation=operation,
            price=amount,
            currency=currency,
            address=street_address,
            city=city,
            total_m2=mapped.get("total_m2"),
            covered_m2=mapped.get("covered_m2"),
            bedrooms=mapped.get("bedrooms"),
            bathrooms=mapped.get("bathrooms"),
            total_rooms=mapped.get("total_rooms"),
            agent_phone=phone_match.group(1) if phone_match else None,
            office_name=self.source_name,
            photos=photos,
            raw=fields,
        )


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
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


class DanielInmobiliariaScraper(ArgenCasasCustomScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://danielinmobiliaria.com.ar", source_name="danielinmobiliaria", delay=delay)
