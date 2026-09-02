"""R. Tavella Propiedades e Inmuebles (Ituzaingó) — third agency on the
legacy ArgenCasas template. See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class TavellaScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.rtavellainmuebles.com", source_name="tavella", delay=delay or 2.0)
