"""Inmobiliaria Rejn (Ituzaingó) — first agency on the older ArgenCasas
template variant. See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class RejnScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        # robots.txt asks for Crawl-delay: 2
        super().__init__(base_url="https://www.inmobiliariarejn.com.ar", source_name="rejn", delay=delay or 2.0)
