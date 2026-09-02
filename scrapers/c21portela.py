"""CENTURY 21 Portela Sabrina (Ituzaingó). See scrapers/century21.py."""

from typing import Optional

from scrapers.century21 import Century21Scraper


class C21PortelaScraper(Century21Scraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(office_slug="85-portela-sabrina", source_name="c21portela", delay=delay)
