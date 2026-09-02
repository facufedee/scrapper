"""Ricciardelli Propiedades (Caseros, Tres de Febrero) — "adprop" platform
(same as Spinelli/Gabriel Basta). See scrapers/adprop.py."""

from typing import Optional

from scrapers.adprop import AdPropScraper


class RicciardelliScraper(AdPropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://ricciardellipropiedades.com", source_name="ricciardelli", delay=delay)
