"""One-time migration: copy every row from the local SQLite DB into Postgres
(Supabase). Preserves primary keys so property_photos.property_id and
price_history.property_id foreign keys still line up, then resets each
Postgres sequence to continue after the copied max id.

Usage:
    DATABASE_URL=postgresql://... python migrate_to_postgres.py

Safe to re-run: each table is emptied (TRUNCATE ... CASCADE) before copying,
so a re-run just replaces Postgres's contents with the current SQLite state
rather than duplicating rows. Run it after the scrapers are idle — this
doesn't touch SQLite, only reads from it, but a table being written to
mid-copy could produce an inconsistent snapshot in Postgres.
"""

import sys

from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import sessionmaker

import config
from db.models import Base, PriceHistory, Property, PropertyPhoto, ScrapeRun

SQLITE_URL = f"sqlite:///{config.DB_PATH}"

TABLES_IN_FK_ORDER = [Property, PropertyPhoto, PriceHistory, ScrapeRun]


def main():
    pg_url = config.DATABASE_URL
    if pg_url.startswith("sqlite"):
        print("DATABASE_URL no está configurada (o apunta a sqlite) — seteala a tu connection string de Supabase antes de correr esto.")
        sys.exit(1)

    print(f"Origen (SQLite): {SQLITE_URL}")
    print(f"Destino (Postgres): {pg_url.split('@')[-1]}")  # don't print credentials

    sqlite_engine = create_engine(SQLITE_URL)
    pg_engine = create_engine(pg_url)

    print("Creando tablas en Postgres si no existen...")
    Base.metadata.create_all(pg_engine)

    SqliteSession = sessionmaker(bind=sqlite_engine)
    PgSession = sessionmaker(bind=pg_engine)

    sqlite_session = SqliteSession()
    pg_session = PgSession()

    try:
        # empty tables in reverse FK order so TRUNCATE CASCADE doesn't complain,
        # then copy in forward FK order so parent rows exist before children
        print("Vaciando tablas destino...")
        for model in reversed(TABLES_IN_FK_ORDER):
            pg_session.execute(text(f'TRUNCATE TABLE "{model.__tablename__}" CASCADE'))
        pg_session.commit()

        for model in TABLES_IN_FK_ORDER:
            rows = sqlite_session.query(model).all()
            print(f"{model.__tablename__}: {len(rows)} filas...")
            if not rows:
                continue

            columns = [c.name for c in model.__table__.columns]
            batch = []
            for row in rows:
                batch.append({col: getattr(row, col) for col in columns})
                if len(batch) >= 1000:
                    pg_session.execute(insert(model.__table__), batch)
                    pg_session.commit()
                    batch = []
            if batch:
                pg_session.execute(insert(model.__table__), batch)
                pg_session.commit()

            # move the identity/serial sequence past the copied max id so the
            # next autoincrement insert doesn't collide with a migrated row
            max_id = max(r.id for r in rows)
            seq_name = f"{model.__tablename__}_id_seq"
            pg_session.execute(text(f"SELECT setval('{seq_name}', :max_id)"), {"max_id": max_id})
            pg_session.commit()

        print("Listo.")
    finally:
        sqlite_session.close()
        pg_session.close()


if __name__ == "__main__":
    main()
