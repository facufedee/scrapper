"""Inmobiliaria Víctor Vende (Ituzaingó) — legacy ArgenCasas template.
See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class VictorVendeScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.victorvende.com.ar", source_name="victorvende", delay=delay or 2.0)
