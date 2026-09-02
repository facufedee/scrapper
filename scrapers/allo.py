"""Nerina Allo Propiedades (Castelar) — third agency on Tokko Broker.
See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class AlloScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.allopropiedades.com.ar", source_name="allo", delay=delay)
