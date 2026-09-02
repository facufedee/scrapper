"""Bruno Inmuebles (Ituzaingó) — legacy ArgenCasas template.
See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class BrunoInmueblesScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://brunoinmuebles.com.ar", source_name="brunoinmuebles", delay=delay or 2.0)
