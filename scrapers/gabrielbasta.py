"""Gabriel Basta (Merlo) — second agency on the "adprop" platform.
See scrapers/adprop.py."""

from typing import Optional

from scrapers.adprop import AdPropScraper


class GabrielBastaScraper(AdPropScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.gabrielbasta.com", source_name="gabrielbasta", delay=delay)
