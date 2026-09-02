"""Ledesma Propiedades (Ituzaingó/CABA) — first agency found on the Navent
"ficha" template. See scrapers/navent_ficha.py."""

from typing import Optional

from scrapers.navent_ficha import NaventFichaScraper


class LedesmaPropScraper(NaventFichaScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://ledesmaprop.com", source_name="ledesmaprop", delay=delay)
