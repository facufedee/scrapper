"""Palacio Propiedades (Ituzaingó) — second agency on Houzez. No Yoast
sitemap here, so discovery falls back to paginating the property archive
(see scrapers/houzez.py)."""

from typing import Optional

from scrapers.houzez import HouzezScraper


class PalacioScraper(HouzezScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.palacioprop.com.ar", source_name="palacio", delay=delay)
