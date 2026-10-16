import pytest

from valuation.domain import (
    Comparable,
    InsufficientComparablesError,
    Subject,
    estimate,
    haversine_km,
    remove_price_outliers,
    select_comparables,
)

SUBJECT = Subject(lat=-34.6037, lon=-58.3816, property_type="apartment", area_m2=50)


def make_comparable(id, price_per_m2, area_m2=50.0, distance_km=0.5, lat=None, lon=None):
    return Comparable(
        id=id,
        source="test",
        url=f"https://example.com/{id}",
        lat=lat if lat is not None else -34.60 - id / 10_000,
        lon=lon if lon is not None else -58.38,
        price_usd=price_per_m2 * area_m2,
        area_m2=area_m2,
        distance_km=distance_km,
    )


def test_haversine_obelisco_to_plaza_de_mayo_is_about_one_km():
    distance = haversine_km(-34.6037, -58.3816, -34.6083, -58.3712)
    assert 1.0 < distance < 1.15


def test_haversine_same_point_is_zero():
    assert haversine_km(-34.6, -58.4, -34.6, -58.4) == 0


def test_select_comparables_drops_listings_with_dissimilar_area():
    similar = make_comparable(1, 2000, area_m2=60)
    too_small = make_comparable(2, 2000, area_m2=25)
    too_big = make_comparable(3, 2000, area_m2=90)

    selected = select_comparables(SUBJECT, [similar, too_small, too_big])

    assert [c.id for c in selected] == [1]


def test_select_comparables_drops_listings_without_usable_price_or_area():
    no_price = make_comparable(1, 0)
    no_area = Comparable(id=2, source="t", url=None, lat=-34.6, lon=-58.38, price_usd=100_000, area_m2=0, distance_km=0.1)
    ok = make_comparable(3, 2000)

    assert [c.id for c in select_comparables(SUBJECT, [no_price, no_area, ok])] == [3]


def test_select_comparables_dedupes_same_listing_published_on_several_portals():
    original = make_comparable(1, 2000, lat=-34.6001, lon=-58.3801)
    same_on_other_portal = make_comparable(2, 2000, lat=-34.60012, lon=-58.38009)
    different = make_comparable(3, 2100)

    selected = select_comparables(SUBJECT, [original, same_on_other_portal, different])

    assert [c.id for c in selected] == [1, 3]


def test_remove_price_outliers_drops_extreme_price_per_m2():
    normal = [make_comparable(i, ppm2) for i, ppm2 in enumerate([1900, 2000, 2100, 2200, 2300], start=1)]
    absurd_cheap = make_comparable(10, 10)
    absurd_expensive = make_comparable(11, 50_000)

    kept = remove_price_outliers(normal + [absurd_cheap, absurd_expensive])

    assert sorted(c.id for c in kept) == [1, 2, 3, 4, 5]


def test_remove_price_outliers_keeps_everything_when_sample_is_too_small():
    few = [make_comparable(1, 1000), make_comparable(2, 9000), make_comparable(3, 2000)]
    assert remove_price_outliers(few) == few


def test_estimate_uses_median_price_per_m2_and_interquartile_range():
    comparables = [make_comparable(i, ppm2) for i, ppm2 in enumerate([2000, 2100, 2200, 2300, 2400], start=1)]

    valuation = estimate(SUBJECT, comparables, radius_km=1.0)

    assert valuation.median_price_per_m2_usd == 2200
    assert valuation.estimated_value_usd == 110_000
    assert valuation.low_usd == 105_000
    assert valuation.high_usd == 115_000
    assert valuation.comparables_count == 5
    assert valuation.radius_km == 1.0


def test_estimate_lists_nearest_comparables_first():
    comparables = [
        make_comparable(1, 2000, distance_km=0.9),
        make_comparable(2, 2100, distance_km=0.1),
        make_comparable(3, 2200, distance_km=0.5),
        make_comparable(4, 2300, distance_km=0.3),
        make_comparable(5, 2400, distance_km=0.7),
    ]

    valuation = estimate(SUBJECT, comparables, radius_km=1.0)

    assert [c.id for c in valuation.comparables] == [2, 4, 3, 5, 1]


def test_estimate_raises_when_there_are_not_enough_comparables():
    comparables = [make_comparable(i, 2000 + i) for i in range(1, 4)]

    with pytest.raises(InsufficientComparablesError) as error:
        estimate(SUBJECT, comparables, radius_km=3.0, min_comparables=5)

    assert error.value.found == 3
    assert error.value.required == 5


@pytest.mark.parametrize(
    "count, radius_km, expected",
    [
        (15, 1.0, "high"),
        (15, 2.0, "medium"),
        (8, 0.5, "medium"),
        (5, 0.5, "low"),
    ],
)
def test_estimate_confidence_depends_on_sample_size_and_radius(count, radius_km, expected):
    comparables = [make_comparable(i, 2000 + i) for i in range(1, count + 1)]
    assert estimate(SUBJECT, comparables, radius_km=radius_km).confidence == expected
