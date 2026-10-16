from sqlalchemy import create_engine, inspect, text

from db.database import init_db
from db.models import Base


def _index_names(engine):
    return {index["name"] for index in inspect(engine).get_indexes("properties")}


def test_init_db_adds_lat_lon_index_to_an_existing_properties_table():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX idx_properties_lat_lon"))  # simulate a DB created before the index

    init_db(engine)
    init_db(engine)  # idempotent

    assert "idx_properties_lat_lon" in _index_names(engine)
