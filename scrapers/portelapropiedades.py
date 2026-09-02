"""Portela Propiedades (Ituzaingó) — Mapaprop. See scrapers/mapaprop.py."""

from typing import Optional

from scrapers.mapaprop import MapapropScraper


class PortelaPropiedadesScraper(MapapropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.portelapropiedades.com.ar", source_name="portelapropiedades", delay=delay)
