"""Morroni Propiedades (Morón) — first agency scraped on the Houzez WordPress
theme. See scrapers/houzez.py for how the platform itself works."""

from typing import Optional

from scrapers.houzez import HouzezScraper


class MorroniScraper(HouzezScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://morronipropiedades.com.ar", source_name="morroni", delay=delay)
