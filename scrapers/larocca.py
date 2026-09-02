"""La Rocca Properties (Villa Bosch, Tres de Febrero) — older ArgenCasas
template variant. See scrapers/argencasas_legacy.py. Ojo: `laroccapropiedades.com`
(no .ar) is a distinct, unrelated agency in Colegiales — this is
laroccapropiedades.com.ar, with a `www.` prefix (the bare apex domain has a
broken TLS cert)."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class LaRoccaScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.laroccapropiedades.com.ar", source_name="larocca", delay=delay)
