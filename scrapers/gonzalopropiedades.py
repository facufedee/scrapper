"""Gonzalo Propiedades (Ituzaingó) — Wasi. See scrapers/wasi.py."""

from typing import Optional

from scrapers.wasi import WasiScraper


class GonzaloPropiedadesScraper(WasiScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://gonzalopropiedades.com.ar", source_name="gonzalopropiedades", delay=delay)
