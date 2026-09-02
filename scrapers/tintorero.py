"""Tintorero Propiedades (Ituzaingó) — Tokko Broker. See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class TintoreroScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.tintorero.com.ar", source_name="tintorero", delay=delay)
