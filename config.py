import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

DB_PATH = os.getenv("SCRAPPER_DB_PATH", str(DATA_DIR / "properties.db"))
# Postgres (Supabase) is the intended production store — the scrapers and the
# Next.js frontend both read/write it directly, no sync step. SQLite stays as
# the zero-setup local fallback for scraper development before DATABASE_URL
# is configured, or for one-off testing.
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH}"

USER_AGENT = os.getenv(
    "SCRAPPER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

REQUEST_TIMEOUT = float(os.getenv("SCRAPPER_TIMEOUT", "20"))
REQUEST_DELAY = float(os.getenv("SCRAPPER_DELAY", "0.6"))
MAX_RETRIES = int(os.getenv("SCRAPPER_MAX_RETRIES", "6"))  # this network has intermittent DNS blips lasting up to ~10s
