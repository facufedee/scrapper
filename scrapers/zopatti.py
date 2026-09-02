"""Zopatti Propiedades (zona oeste) — same ArgenCasas custom template as
Daniel Inmobiliaria. See scrapers/danielinmobiliaria.py."""

from typing import Optional

from scrapers.danielinmobiliaria import ArgenCasasCustomScraper


class ZopattiScraper(ArgenCasasCustomScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://zopatti.com", source_name="zopatti", delay=delay)
