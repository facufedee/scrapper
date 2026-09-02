"""Repetto Propiedades (Ituzaingó) — Wasi. See scrapers/wasi.py."""

from typing import Optional

from scrapers.wasi import WasiScraper


class RepettoPropScraper(WasiScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://repettoprop.com.ar", source_name="repettoprop", delay=delay)
