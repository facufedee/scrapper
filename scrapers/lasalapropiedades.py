"""Lasala Propiedades (Ituzaingó) — Wasi. See scrapers/wasi.py."""

from typing import Optional

from scrapers.wasi import WasiScraper


class LasalaPropiedadesScraper(WasiScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://lasalapropiedades.com.ar", source_name="lasalapropiedades", delay=delay)
