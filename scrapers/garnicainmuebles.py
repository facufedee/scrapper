"""Garnica Inmuebles (Ituzaingó) — Mapaprop. See scrapers/mapaprop.py."""

from typing import Optional

from scrapers.mapaprop import MapapropScraper


class GarnicaInmueblesScraper(MapapropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.garnicainmuebles.com", source_name="garnicainmuebles", delay=delay)
