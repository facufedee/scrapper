"""CENTURY 21 Freda (Morón/Castelar). See scrapers/century21.py."""

from typing import Optional

from scrapers.century21 import Century21Scraper


class C21FredaScraper(Century21Scraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(office_slug="96-freda", source_name="c21freda", delay=delay)
