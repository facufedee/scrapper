"""Inmobiliaria D'Eramo (Ciudadela, Tres de Febrero) — older ArgenCasas
template variant, same as Rejn/Tavella. See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class DEramoScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        # robots.txt asks for Crawl-delay: 2
        super().__init__(
            base_url="https://www.inmobiliariaderamo.com.ar", source_name="deramo", delay=delay or 2.0
        )
