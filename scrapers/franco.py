"""Franco Property Organization (Santos Lugares, Tres de Febrero) — Navent
"ficha" template, same backend as Ledesma Propiedades. See
scrapers/navent_ficha.py."""

from typing import Optional

from scrapers.navent_ficha import NaventFichaScraper


class FrancoScraper(NaventFichaScraper):
    def __init__(self, delay: Optional[float] = None):
        super().__init__(base_url="https://inmobiliariafranco.com.ar", source_name="franco", delay=delay)
