"""Taburet Propiedades (Ituzaingó) — first agency on Tokko Broker.
See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class TaburetScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.taburet.com.ar", source_name="taburet", delay=delay)
