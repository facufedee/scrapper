"""Reads candidate listings from the properties table and adapts them to the domain.

Raw rows are normalized here (currency, property type, area) so the domain only ever
sees clean, comparable data, and the stored data does not need to be rewritten.
"""

import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Property
from pipeline.normalize import canonical_property_type, normalize_currency
from valuation.domain import Comparable, haversine_km

KM_PER_LAT_DEGREE = 111.32


def _area_m2(property_type: str, row) -> Optional[float]:
    # Land is priced by lot size; everything else by built area.
    if property_type == "land":
        return row.land_m2 or row.total_m2
    return row.covered_m2 or row.total_m2


def find_candidates(
    session: Session, lat: float, lon: float, radius_km: float, property_type: str
) -> list[Comparable]:
    """Sale listings priced in USD of the given canonical type within radius_km."""
    lat_delta = radius_km / KM_PER_LAT_DEGREE
    lon_delta = radius_km / (KM_PER_LAT_DEGREE * math.cos(math.radians(lat)))

    # Bounding box in SQL (cheap), exact circle and normalization in Python.
    rows = session.execute(
        select(
            Property.id,
            Property.source,
            Property.url,
            Property.lat,
            Property.lon,
            Property.price,
            Property.currency,
            Property.property_type,
            Property.covered_m2,
            Property.total_m2,
            Property.land_m2,
            Property.bedrooms,
            Property.total_rooms,
        ).where(
            Property.operation == "sale",
            Property.price > 0,
            Property.lat.between(lat - lat_delta, lat + lat_delta),
            Property.lon.between(lon - lon_delta, lon + lon_delta),
        )
    ).all()

    candidates: list[Comparable] = []
    for row in rows:
        if normalize_currency(row.currency) != "USD":
            continue
        if canonical_property_type(row.property_type) != property_type:
            continue
        area = _area_m2(property_type, row)
        if not area:
            continue
        distance = haversine_km(lat, lon, row.lat, row.lon)
        if distance > radius_km:
            continue
        candidates.append(
            Comparable(
                id=row.id,
                source=row.source,
                url=row.url,
                lat=row.lat,
                lon=row.lon,
                price_usd=row.price,
                area_m2=area,
                distance_km=round(distance, 3),
                bedrooms=row.bedrooms,
                total_rooms=row.total_rooms,
            )
        )
    return candidates
