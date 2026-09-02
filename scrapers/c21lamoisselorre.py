"""CENTURY 21 Lamoisse Lorré (Ituzaingó). See scrapers/century21.py."""

from typing import Optional

from scrapers.century21 import Century21Scraper


class C21LamoisseLorreScraper(Century21Scraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(office_slug="94-lamoisse-lorre", source_name="c21lamoisselorre", delay=delay)
