"""VR Propiedades (Ituzaingó) — legacy ArgenCasas template.
See scrapers/argencasas_legacy.py."""

from typing import Optional

from scrapers.argencasas_legacy import ArgenCasasLegacyScraper


class VrPropiedadesScraper(ArgenCasasLegacyScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://www.vrpropiedades.com.ar", source_name="vrpropiedades", delay=delay or 2.0)
