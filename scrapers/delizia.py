"""Delizia Propiedades (Ituzaingó) — first agency on RealHomes.
See scrapers/realhomes.py."""

from typing import Optional

from scrapers.realhomes import RealHomesScraper


class DeliziaScraper(RealHomesScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://delizia.com.ar", source_name="delizia", delay=delay)
