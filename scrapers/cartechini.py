"""Cartechini Propiedades (Ituzaingó) — "adprop" platform, same as
Spinelli/Gabriel Basta. See scrapers/adprop.py."""

from typing import Optional

from scrapers.adprop import AdPropScraper


class CartechiniScraper(AdPropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://cartechini.com.ar", source_name="cartechini", delay=delay)
