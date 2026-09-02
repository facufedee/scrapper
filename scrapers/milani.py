"""Carlos Milani (Castelar) — third agency on Houzez. No Yoast sitemap
(falls back to archive pagination). See scrapers/houzez.py."""

from typing import Optional

from scrapers.houzez import HouzezScraper


class MilaniScraper(HouzezScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.carlosmilanicastelar.com", source_name="milani", delay=delay)
