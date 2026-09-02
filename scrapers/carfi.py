"""Eduardo J. Carfi Propiedades (Castelar) — second agency on Tokko Broker.
See scrapers/tokko.py. (Julio Carfi, the other brother's agency, runs a
different platform — see scrapers/juliocarfi.py.)"""

from typing import Optional

from scrapers.tokko import TokkoScraper


class CarfiScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.carfi.com.ar", source_name="carfi", delay=delay)
