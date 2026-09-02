"""González Abella Propiedades (Ituzaingó) — Mapaprop. See scrapers/mapaprop.py."""

from typing import Optional

from scrapers.mapaprop import MapapropScraper


class GonzalezAbellaScraper(MapapropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.gonzalezabella.com.ar", source_name="gonzalezabella", delay=delay)
