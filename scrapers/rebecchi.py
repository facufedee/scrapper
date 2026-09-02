"""Rebecchi Propiedades (Ituzaingó) — Tokko Broker. See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class RebecchiScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.rebecchipropiedades.com.ar", source_name="rebecchi", delay=delay)
