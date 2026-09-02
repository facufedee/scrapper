"""MSV Inmobiliaria (Ituzaingó) — Mapaprop. See scrapers/mapaprop.py."""

from typing import Optional

from scrapers.mapaprop import MapapropScraper


class MsvInmobiliariaScraper(MapapropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.msvinmobiliaria.com", source_name="msvinmobiliaria", delay=delay)
