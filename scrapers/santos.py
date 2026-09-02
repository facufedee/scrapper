"""Santos Propiedades (Haedo) — second agency on the legacy ArgenCasas
template. See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class SantosScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.santospropiedades.com.ar", source_name="santos", delay=delay or 2.0)
