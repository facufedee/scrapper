"""Gastón Escriña Propiedades (Ituzaingó) — Tokko Broker. See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class GescrinaScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.gescrina.com.ar", source_name="gescrina", delay=delay)
