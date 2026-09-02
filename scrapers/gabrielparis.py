"""Gabriel Paris Asesor Inmobiliario (Ituzaingó) — Xintel. See scrapers/xintel.py."""

from typing import Optional

from scrapers.xintel import XintelScraper


class GabrielParisScraper(XintelScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(
            base_url="https://gabrielparis.com.ar",
            source_name="gabrielparis",
            tenant_code="GPA",
            api_key="G4M8D89UMHTNUKS4ZUDGRZJ32",
            delay=delay,
        )
