"""Magallanes Estudio Inmobiliario (Ituzaingó) — Tokko Broker. See scrapers/tokko.py."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class MagallanesScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.magallanesprop.com.ar", source_name="magallanes", delay=delay)
