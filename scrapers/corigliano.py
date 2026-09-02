"""Corigliano Propiedades (Ituzaingó) — second agency on RealHomes.
See scrapers/realhomes.py."""

from typing import Optional

from scrapers.realhomes import RealHomesScraper


class CoriglianoScraper(RealHomesScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.coriglianopropiedades.com.ar", source_name="corigliano", delay=delay)
