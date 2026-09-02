"""Pintimalli Propiedades (Caseros, Tres de Febrero) — Tokko Broker.
See scrapers/tokko.py. Same family business as "José Pintimalli Propiedades"
(josepintimalli.com.ar) — identical footer/history, same site content."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class PintimalliScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.pintimallipropiedades.com", source_name="pintimalli", delay=delay)
