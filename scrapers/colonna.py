"""N.J. Colonna Properties (Sáenz Peña, Tres de Febrero) — Tokko Broker.
See scrapers/tokko.py. `colonna.com.ar` 301-redirects to this tuinmobiliaria
subdomain, which is the site actually served (confirmed static.tokkobroker.com
in its Content-Security-Policy header)."""

from typing import Optional

from scrapers.tokko import TokkoScraper


class ColonnaScraper(TokkoScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(
            base_url="https://inmobiliariacolonna.tuinmobiliaria.com.ar", source_name="colonna", delay=delay
        )
