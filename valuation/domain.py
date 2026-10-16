"""Pure valuation logic: no database, no HTTP. Given a subject property and candidate
listings around it, pick comparable listings and estimate a market asking value.

Method (kept deliberately simple so it can be explained to a client):
1. keep candidates with a usable price and a similar area (default +/-40%),
2. drop the same listing published on several portals,
3. drop price-per-m2 outliers (Tukey IQR fences),
4. estimate = median USD/m2 x subject area, range = interquartile USD/m2 x subject area.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Optional

EARTH_RADIUS_KM = 6371.0
MIN_SAMPLE_FOR_OUTLIER_REMOVAL = 4
NEAREST_COMPARABLES_LISTED = 10


@dataclass(frozen=True)
class Subject:
    lat: float
    lon: float
    property_type: str  # canonical type, see pipeline.normalize.canonical_property_type
    area_m2: float


@dataclass(frozen=True)
class Comparable:
    id: int
    source: str
    url: Optional[str]
    lat: float
    lon: float
    price_usd: float
    area_m2: float
    distance_km: float
    bedrooms: Optional[int] = None
    total_rooms: Optional[int] = None

    @property
    def price_per_m2(self) -> float:
        return self.price_usd / self.area_m2


@dataclass(frozen=True)
class Valuation:
    estimated_value_usd: float
    low_usd: float
    high_usd: float
    median_price_per_m2_usd: float
    comparables_count: int
    radius_km: float
    confidence: str  # high, medium, low
    comparables: tuple[Comparable, ...]  # nearest ones, for transparency


class InsufficientComparablesError(Exception):
    def __init__(self, found: int, required: int):
        super().__init__(f"Found {found} comparable listings, at least {required} are required")
        self.found = found
        self.required = required


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _dedupe_key(comparable: Comparable) -> tuple:
    # Same building (~10 m), same price and same area: the same listing on another portal.
    return (
        round(comparable.lat, 4),
        round(comparable.lon, 4),
        round(comparable.price_usd),
        round(comparable.area_m2),
    )


def select_comparables(
    subject: Subject, candidates: list[Comparable], area_tolerance: float = 0.4
) -> list[Comparable]:
    min_area = subject.area_m2 * (1 - area_tolerance)
    max_area = subject.area_m2 * (1 + area_tolerance)

    selected: list[Comparable] = []
    seen: set[tuple] = set()
    for candidate in candidates:
        if candidate.price_usd <= 0 or candidate.area_m2 <= 0:
            continue
        if not min_area <= candidate.area_m2 <= max_area:
            continue
        key = _dedupe_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
    return selected


def remove_price_outliers(comparables: list[Comparable]) -> list[Comparable]:
    if len(comparables) < MIN_SAMPLE_FOR_OUTLIER_REMOVAL:
        return comparables
    q1, _, q3 = statistics.quantiles([c.price_per_m2 for c in comparables], n=4, method="inclusive")
    fence = 1.5 * (q3 - q1)
    return [c for c in comparables if q1 - fence <= c.price_per_m2 <= q3 + fence]


def _confidence(count: int, radius_km: float) -> str:
    if count >= 15 and radius_km <= 1.0:
        return "high"
    if count >= 8:
        return "medium"
    return "low"


def estimate(
    subject: Subject, comparables: list[Comparable], radius_km: float, min_comparables: int = 5
) -> Valuation:
    """Estimate the subject's asking value from already-selected comparables."""
    if len(comparables) < min_comparables:
        raise InsufficientComparablesError(found=len(comparables), required=min_comparables)

    prices_per_m2 = [c.price_per_m2 for c in comparables]
    median = statistics.median(prices_per_m2)
    q1, _, q3 = statistics.quantiles(prices_per_m2, n=4, method="inclusive")
    nearest = sorted(comparables, key=lambda c: c.distance_km)[:NEAREST_COMPARABLES_LISTED]

    return Valuation(
        estimated_value_usd=round(median * subject.area_m2, -3),
        low_usd=round(q1 * subject.area_m2, -3),
        high_usd=round(q3 * subject.area_m2, -3),
        median_price_per_m2_usd=round(median),
        comparables_count=len(comparables),
        radius_km=radius_km,
        confidence=_confidence(len(comparables), radius_km),
        comparables=tuple(nearest),
    )
