"""Inmobiliaria Spinelli (Haedo) — first agency on the "adprop" platform.
See scrapers/adprop.py."""

from typing import Optional

from scrapers.adprop import AdPropScraper


class SpinelliScraper(AdPropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.spinelliprophaedo.com.ar", source_name="spinelli", delay=delay)
