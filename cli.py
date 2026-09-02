import argparse
import inspect
import logging
import sys

import config
from db.database import get_session, init_db
from db.models import ScrapeRun, utcnow
from pipeline.upsert import upsert_property
from scrapers.allo import AlloScraper
from scrapers.arenaprop import ArenaPropScraper
from scrapers.argenprop import ArgenpropScraper
from scrapers.brunoinmuebles import BrunoInmueblesScraper
from scrapers.c21freda import C21FredaScraper
from scrapers.c21lamoisselorre import C21LamoisseLorreScraper
from scrapers.c21portela import C21PortelaScraper
from scrapers.cabrera import CabreraScraper
from scrapers.carfi import CarfiScraper
from scrapers.carlucci import CarlucciScraper
from scrapers.cartechini import CartechiniScraper
from scrapers.colonna import ColonnaScraper
from scrapers.corigliano import CoriglianoScraper
from scrapers.danielinmobiliaria import DanielInmobiliariaScraper
from scrapers.delizia import DeliziaScraper
from scrapers.defazio import DeFazioScraper
from scrapers.deramo import DEramoScraper
from scrapers.dicasoli import DiCasoliScraper
from scrapers.fabianamtripe import FabianaMTripeScraper
from scrapers.ferrero import FerreroScraper
from scrapers.fparadela import FParadelaScraper
from scrapers.franco import FrancoScraper
from scrapers.gabrielbasta import GabrielBastaScraper
from scrapers.gabrielparis import GabrielParisScraper
from scrapers.garnicainmuebles import GarnicaInmueblesScraper
from scrapers.gescrina import GescrinaScraper
from scrapers.gonzalezabella import GonzalezAbellaScraper
from scrapers.gonzalopropiedades import GonzaloPropiedadesScraper
from scrapers.grupovaccaro import GrupoVaccaroScraper
from scrapers.juliocarfi import JulioCarfiScraper
from scrapers.lacoste import LacosteScraper
from scrapers.larocca import LaRoccaScraper
from scrapers.lasalapropiedades import LasalaPropiedadesScraper
from scrapers.ledesmaprop import LedesmaPropScraper
from scrapers.magallanes import MagallanesScraper
from scrapers.matiasszpira import MatiasSzpiraScraper
from scrapers.mercadolibre_manual import parse_search_results
from scrapers.milani import MilaniScraper
from scrapers.mjcarabelli import MjCarabelliScraper
from scrapers.montesdeoca import MontesDeOcaScraper
from scrapers.moreleloir import MoreLeloirScraper
from scrapers.morroni import MorroniScraper
from scrapers.msvinmobiliaria import MsvInmobiliariaScraper
from scrapers.palacio import PalacioScraper
from scrapers.piccione import PiccioneScraper
from scrapers.pintimalli import PintimalliScraper
from scrapers.portelapropiedades import PortelaPropiedadesScraper
from scrapers.rebecchi import RebecchiScraper
from scrapers.rejn import RejnScraper
from scrapers.repettoprop import RepettoPropScraper
from scrapers.remax import RemaxScraper
from scrapers.ricciardelli import RicciardelliScraper
from scrapers.santos import SantosScraper
from scrapers.scarinci import ScarinciScraper
from scrapers.sgonzalez import SGonzalezScraper
from scrapers.taburet import TaburetScraper
from scrapers.tavella import TavellaScraper
from scrapers.tintorero import TintoreroScraper
from scrapers.spinelli import SpinelliScraper
from scrapers.victorvende import VictorVendeScraper
from scrapers.vrpropiedades import VrPropiedadesScraper
from scrapers.zonaprop import ZonaPropScraper
from scrapers.zopatti import ZopattiScraper

SCRAPERS = {
    "remax": RemaxScraper,
    "zonaprop": ZonaPropScraper,
    "argenprop": ArgenpropScraper,
    "ferrero": FerreroScraper,
    "carlucci": CarlucciScraper,
    "morroni": MorroniScraper,
    "palacio": PalacioScraper,
    "rejn": RejnScraper,
    "santos": SantosScraper,
    "tavella": TavellaScraper,
    "taburet": TaburetScraper,
    "carfi": CarfiScraper,
    "lacoste": LacosteScraper,
    "juliocarfi": JulioCarfiScraper,
    "milani": MilaniScraper,
    "allo": AlloScraper,
    "spinelli": SpinelliScraper,
    "gabrielbasta": GabrielBastaScraper,
    "magallanes": MagallanesScraper,
    "rebecchi": RebecchiScraper,
    "arenaprop": ArenaPropScraper,
    "gescrina": GescrinaScraper,
    "mjcarabelli": MjCarabelliScraper,
    "tintorero": TintoreroScraper,
    "victorvende": VictorVendeScraper,
    "vrpropiedades": VrPropiedadesScraper,
    "delizia": DeliziaScraper,
    "corigliano": CoriglianoScraper,
    "dicasoli": DiCasoliScraper,
    "gonzalopropiedades": GonzaloPropiedadesScraper,
    "repettoprop": RepettoPropScraper,
    "lasalapropiedades": LasalaPropiedadesScraper,
    "brunoinmuebles": BrunoInmueblesScraper,
    "cartechini": CartechiniScraper,
    "piccione": PiccioneScraper,
    "msvinmobiliaria": MsvInmobiliariaScraper,
    "portelapropiedades": PortelaPropiedadesScraper,
    "garnicainmuebles": GarnicaInmueblesScraper,
    "gonzalezabella": GonzalezAbellaScraper,
    "grupovaccaro": GrupoVaccaroScraper,
    "fabianamtripe": FabianaMTripeScraper,
    "ledesmaprop": LedesmaPropScraper,
    "gabrielparis": GabrielParisScraper,
    "fparadela": FParadelaScraper,
    "danielinmobiliaria": DanielInmobiliariaScraper,
    "matiasszpira": MatiasSzpiraScraper,
    "sgonzalez": SGonzalezScraper,
    "zopatti": ZopattiScraper,
    "moreleloir": MoreLeloirScraper,
    "c21lamoisselorre": C21LamoisseLorreScraper,
    "c21freda": C21FredaScraper,
    "c21portela": C21PortelaScraper,
    "colonna": ColonnaScraper,
    "pintimalli": PintimalliScraper,
    "larocca": LaRoccaScraper,
    "cabrera": CabreraScraper,
    "franco": FrancoScraper,
    "montesdeoca": MontesDeOcaScraper,
    "deramo": DEramoScraper,
    "ricciardelli": RicciardelliScraper,
    "defazio": DeFazioScraper,
    "scarinci": ScarinciScraper,
}

COMMIT_EVERY = 20  # short transactions so concurrent scrapers don't block each other for minutes


def setup_logging():
    # Windows consoles default stdout to cp1252, which can't encode emoji or
    # other characters that show up in scraped text (site data is full
    # surprises) — reconfigure to UTF-8 with a safe fallback instead of
    # letting a log line crash the whole run.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_DIR / "scrapper.log", encoding="utf-8"),
        ],
    )


def _make_scraper(scraper_cls, page_size: int):
    accepted = inspect.signature(scraper_cls.__init__).parameters
    kwargs = {}
    if "page_size" in accepted:
        kwargs["page_size"] = page_size
    return scraper_cls(**kwargs)


def _run_one(session, run_logger, scraper, source: str, operation: str, max_pages: int | None):
    run_row = ScrapeRun(source=source, operation=operation, started_at=utcnow(), status="running")
    session.add(run_row)
    session.commit()

    found = new_count = updated_count = 0
    try:
        for item in scraper.fetch_listings(operation=operation, max_pages=max_pages):
            is_new = upsert_property(session, item)
            found += 1
            if is_new:
                new_count += 1
            else:
                updated_count += 1

            if found % COMMIT_EVERY == 0:
                session.commit()
                run_logger.info(
                    "progress source=%s op=%s found=%s new=%s updated=%s",
                    source, operation, found, new_count, updated_count,
                )

        session.commit()
        run_row.status = "success"
    except Exception as exc:
        session.rollback()
        run_row.status = "failed"
        run_row.error = str(exc)
        run_logger.exception("Scrape run failed source=%s operation=%s", source, operation)
    finally:
        run_row.items_found = found
        run_row.items_new = new_count
        run_row.items_updated = updated_count
        run_row.finished_at = utcnow()
        session.commit()

    run_logger.info(
        "DONE source=%s operation=%s found=%s new=%s updated=%s status=%s",
        source, operation, found, new_count, updated_count, run_row.status,
    )


def run(source: str, operation_arg: str, max_pages: int | None, page_size: int):
    logger = logging.getLogger("cli")
    init_db()
    scraper_cls = SCRAPERS[source]
    scraper = _make_scraper(scraper_cls, page_size)

    if operation_arg == "all" and scraper.all_in_one:
        operations = ["all"]
    elif operation_arg == "all":
        operations = ["sale", "rent", "temporal"]
    else:
        operations = [operation_arg]

    try:
        for operation in operations:
            session = get_session()
            try:
                _run_one(session, logger, scraper, source, operation, max_pages)
            finally:
                session.close()
    finally:
        scraper.close()


def ingest_ml_paste(path: str):
    logger = logging.getLogger("cli")
    init_db()

    with open(path, encoding="utf-8") as f:
        text = f.read()
    items = parse_search_results(text, source_url=path)
    logger.info("parsed %s items from %s", len(items), path)

    session = get_session()
    run_row = ScrapeRun(source="mercadolibre", operation="sale", started_at=utcnow(), status="running")
    session.add(run_row)
    session.commit()

    found = new_count = updated_count = 0
    try:
        for item in items:
            is_new = upsert_property(session, item)
            found += 1
            new_count += is_new
            updated_count += not is_new
        session.commit()
        run_row.status = "success"
    except Exception as exc:
        session.rollback()
        run_row.status = "failed"
        run_row.error = str(exc)
        logger.exception("MercadoLibre paste ingest failed")
    finally:
        run_row.items_found = found
        run_row.items_new = new_count
        run_row.items_updated = updated_count
        run_row.finished_at = utcnow()
        session.commit()
        session.close()

    logger.info("DONE mercadolibre paste found=%s new=%s updated=%s status=%s", found, new_count, updated_count, run_row.status)


def main():
    parser = argparse.ArgumentParser(description="Scraper de portales inmobiliarios -> base de datos local")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Ejecuta un scraper y guarda los resultados en la DB")
    run_parser.add_argument("source", choices=SCRAPERS.keys())
    run_parser.add_argument(
        "--operation", choices=["sale", "rent", "temporal", "all"], default="sale",
        help="Tipo de operación a scrapear (default: sale)",
    )
    run_parser.add_argument("--max-pages", type=int, default=None, help="Límite de páginas/ítems (para pruebas)")
    run_parser.add_argument("--page-size", type=int, default=100, help="Ítems por página (solo aplica a scrapers con API paginada)")

    ingest_parser = sub.add_parser(
        "ingest-ml",
        help="Carga a la DB el contenido de una página de resultados de MercadoLibre Inmuebles que vos pegaste en un archivo de texto",
    )
    ingest_parser.add_argument("path", help="Archivo de texto con el contenido pegado de la página")

    args = parser.parse_args()
    setup_logging()

    if args.command == "run":
        run(args.source, args.operation, args.max_pages, args.page_size)
    elif args.command == "ingest-ml":
        ingest_ml_paste(args.path)


if __name__ == "__main__":
    main()
