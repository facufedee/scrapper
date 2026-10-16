from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import config
from db.models import Base, Property

_is_sqlite = config.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    # Postgres (Supabase) connections idle out / get recycled by the pooler;
    # pre_ping avoids handing out a dead connection from the pool instead of
    # erroring on the next query.
    pool_pre_ping=not _is_sqlite,
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        # WAL lets one writer and multiple readers work at the same time instead of
        # locking the whole file; busy_timeout makes a writer retry for a while
        # instead of immediately raising "database is locked" on brief overlaps
        # (e.g. two scrapers, or a scraper and an app query, running at once).
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Indexes declared after the table already existed in deployed databases. create_all()
# only creates indexes together with a new table, so these are added explicitly. Not all
# model indexes are ensured here: older ones exist under hand-made names (idx_*) and would
# be duplicated under SQLAlchemy's default names (ix_*).
_LATE_INDEXES = ("idx_properties_lat_lon",)


def init_db(bind=None) -> None:
    bind = bind or engine
    Base.metadata.create_all(bind)
    for index in Property.__table__.indexes:
        if index.name in _LATE_INDEXES:
            index.create(bind, checkfirst=True)


def get_session():
    return SessionLocal()
