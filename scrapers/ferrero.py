"""Ferrero Propiedades (Ituzaingó) — first agency scraped on the ArgenCasas
platform. See scrapers/argencasas.py for how the platform itself works."""

from typing import Optional

from scrapers.argencasas import ArgenCasasScraper


class FerreroScraper(ArgenCasasScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://inmobiliariaferrero.com", source_name="ferrero", delay=delay)
