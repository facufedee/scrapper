"""Inmobiliaria Di Casoli (Ituzaingó) — first agency on Wasi. See scrapers/wasi.py."""

from typing import Optional

from scrapers.wasi import WasiScraper


class DiCasoliScraper(WasiScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://dicasoli.com.ar", source_name="dicasoli", delay=delay)
