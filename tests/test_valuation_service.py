import itertools

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Property
from valuation.domain import InsufficientComparablesError, Subject
from valuation.service import value_property

ORIGIN_LAT, ORIGIN_LON = -34.6037, -58.3816
KM_PER_LAT_DEGREE = 111.32

_ids = itertools.count(1)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def add_listing(session, km_north=0.3, price=100_000, covered_m2=50, **overrides):
    listing_id = next(_ids)
    values = dict(
        source="test",
        source_id=str(listing_id),
        url=f"https://example.com/{listing_id}",
        operation="sale",
        property_type="departamento_estandar",
        price=price,
        currency="USD",
        covered_m2=covered_m2,
        lat=ORIGIN_LAT + km_north / KM_PER_LAT_DEGREE,
        lon=ORIGIN_LON + listing_id / 1_000_000,  # keep listings distinct for dedupe
    )
    values.update(overrides)
    session.add(Property(**values))
    session.commit()


def apartment(area_m2=50):
    return Subject(lat=ORIGIN_LAT, lon=ORIGIN_LON, property_type="apartment", area_m2=area_m2)


def test_values_property_from_nearby_listings_of_the_same_type(session):
    for price in (95_000, 100_000, 105_000, 110_000, 115_000):
        add_listing(session, price=price)

    valuation = value_property(session, apartment())

    assert valuation.estimated_value_usd == 105_000
    assert valuation.comparables_count == 5
    assert valuation.radius_km == 3.0  # fewer than the target count, so it searched the widest radius


def test_ignores_listings_that_are_not_comparable(session):
    for price in (95_000, 100_000, 105_000, 110_000, 115_000):
        add_listing(session, price=price)
    add_listing(session, price=900_000, operation="rent")
    add_listing(session, price=900_000, currency="ARS")
    add_listing(session, price=900_000, property_type="casa")
    add_listing(session, price=900_000, km_north=10)
    add_listing(session, price=900_000, lat=None, lon=None)

    valuation = value_property(session, apartment())

    assert valuation.comparables_count == 5
    assert valuation.estimated_value_usd == 105_000


def test_understands_raw_type_and_currency_spellings_from_any_source(session):
    for price in (95_000, 100_000, 105_000, 110_000, 115_000):
        add_listing(session, price=price, property_type="DEPARTAMENTO", currency="US$")

    assert value_property(session, apartment()).comparables_count == 5


def test_uses_total_area_when_covered_area_is_missing(session):
    for price in (95_000, 100_000, 105_000, 110_000, 115_000):
        add_listing(session, price=price, covered_m2=None, total_m2=50)

    assert value_property(session, apartment()).estimated_value_usd == 105_000


def test_values_land_by_land_area(session):
    for price in (95_000, 100_000, 105_000, 110_000, 115_000):
        add_listing(session, price=price, property_type="LOTE", covered_m2=None, land_m2=300)

    land = Subject(lat=ORIGIN_LAT, lon=ORIGIN_LON, property_type="land", area_m2=300)

    assert value_property(session, land).estimated_value_usd == 105_000


def test_stops_at_the_smallest_radius_with_enough_comparables(session):
    for i in range(10):
        add_listing(session, km_north=0.3, price=100_000 + i * 1_000)
    for i in range(10):
        add_listing(session, km_north=1.5, price=200_000 + i * 1_000)

    valuation = value_property(session, apartment())

    assert valuation.radius_km == 0.5
    assert valuation.comparables_count == 10


def test_expands_radius_when_nearby_comparables_are_scarce(session):
    for i in range(3):
        add_listing(session, km_north=0.3, price=100_000 + i * 1_000)
    for i in range(10):
        add_listing(session, km_north=1.5, price=100_000 + i * 1_000)

    valuation = value_property(session, apartment())

    assert valuation.radius_km == 2.0
    assert valuation.comparables_count == 13


def test_raises_when_not_enough_comparables_within_max_radius(session):
    for price in (100_000, 110_000):
        add_listing(session, price=price)

    with pytest.raises(InsufficientComparablesError):
        value_property(session, apartment())
