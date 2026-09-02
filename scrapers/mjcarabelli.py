"""Maria Jose Carabelli Propiedades (Ituzaingó) — Tokko Broker. See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class MjCarabelliScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.mjcarabelli.com", source_name="mjcarabelli", delay=delay)
