"""Valuation use case: the single entry point the future HTTP API will call."""

from sqlalchemy.orm import Session

from valuation.domain import Subject, Valuation, estimate, remove_price_outliers, select_comparables
from valuation.repository import find_candidates

DEFAULT_RADII_KM = (0.5, 1.0, 2.0, 3.0)
TARGET_COMPARABLES = 10
MIN_COMPARABLES = 5


def value_property(
    session: Session,
    subject: Subject,
    radii_km: tuple[float, ...] = DEFAULT_RADII_KM,
    target_comparables: int = TARGET_COMPARABLES,
    min_comparables: int = MIN_COMPARABLES,
) -> Valuation:
    """Estimate the subject's asking value, searching the smallest radius that yields
    enough comparables. Raises InsufficientComparablesError if even the widest radius
    has fewer than min_comparables."""
    # One query for the widest radius; narrower radii are filtered in memory.
    candidates = find_candidates(session, subject.lat, subject.lon, max(radii_km), subject.property_type)

    comparables = []
    radius_km = radii_km[0]
    for radius_km in sorted(radii_km):
        within_radius = [c for c in candidates if c.distance_km <= radius_km]
        comparables = remove_price_outliers(select_comparables(subject, within_radius))
        if len(comparables) >= target_comparables:
            break

    return estimate(subject, comparables, radius_km=radius_km, min_comparables=min_comparables)
