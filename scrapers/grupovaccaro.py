"""Grupo Vaccaro (Ituzaingó/Moreno) — Xintel. See scrapers/xintel.py."""

from typing import Optional

from scrapers.xintel import XintelScraper


class GrupoVaccaroScraper(XintelScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(
            base_url="https://grupovaccaro.com",
            source_name="grupovaccaro",
            tenant_code="VCO",
            api_key="Y91YBTWUUWBXWB6KZGZAOJMSP",
            delay=delay,
        )
