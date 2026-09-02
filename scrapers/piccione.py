"""Piccione Propiedades (Ituzaingó) — same platform as Carlucci. See scrapers/carlucci.py."""

from typing import Optional

from scrapers.carlucci import CarlucciPlatformScraper


class PiccioneScraper(CarlucciPlatformScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://piccioneprop.com.ar", source_name="piccione", delay=delay)
