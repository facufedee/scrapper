import itertools

import pytest
from fastapi.testclient import TestClient

from api.keys import generate_api_key, hash_api_key
from api.main import create_app
from api.settings import ApiSettings, parse_api_keys
from db.models import Property

ORIGIN_LAT, ORIGIN_LON = -34.6037, -58.3816
KM_PER_LAT_DEGREE = 111.32

TEST_KEY = "zano_test_key"
VALID_BODY = {"lat": ORIGIN_LAT, "lon": ORIGIN_LON, "property_type": "apartment", "area_m2": 50}


@pytest.fixture
def client(session_factory):
    settings = ApiSettings(api_keys={hash_api_key(TEST_KEY): "zetaprop"})
    app = create_app(settings=settings, session_factory=session_factory)
    return TestClient(app, headers={"X-API-Key": TEST_KEY})


def seed_listings(session_factory, prices=(95_000, 100_000, 105_000, 110_000, 115_000)):
    ids = itertools.count(1)
    with session_factory() as session:
        for price in prices:
            listing_id = next(ids)
            session.add(
                Property(
                    source="remax",
                    source_id=str(listing_id),
                    url=f"https://example.com/{listing_id}",
                    operation="sale",
                    property_type="departamento_estandar",
                    price=price,
                    currency="USD",
                    covered_m2=50,
                    lat=ORIGIN_LAT + 0.3 / KM_PER_LAT_DEGREE,
                    lon=ORIGIN_LON + listing_id / 1_000_000,
                )
            )
        session.commit()


def test_health_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valuation_returns_estimate_range_and_comparables(client, session_factory):
    seed_listings(session_factory)

    response = client.post("/v1/valuations", json=VALID_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["estimated_value_usd"] == 105_000
    assert body["range"] == {"low_usd": 100_000, "high_usd": 110_000}
    assert body["median_price_per_m2_usd"] == 2_100
    assert body["comparables_count"] == 5
    assert body["search_radius_km"] == 3.0
    assert body["confidence"] == "low"
    assert len(body["comparables"]) == 5
    assert set(body["comparables"][0]) == {
        "source",
        "url",
        "distance_km",
        "price_usd",
        "area_m2",
        "price_per_m2_usd",
        "bedrooms",
        "total_rooms",
    }
    assert "asking prices" in body["disclaimer"]


def test_valuation_reports_insufficient_comparables_as_unprocessable(client, session_factory):
    seed_listings(session_factory, prices=(100_000, 110_000))

    response = client.post("/v1/valuations", json=VALID_BODY)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "insufficient_comparables"
    assert detail["found"] == 2
    assert detail["required"] == 5


@pytest.mark.parametrize(
    "override",
    [
        {"lat": 91},
        {"lon": -181},
        {"area_m2": 0},
        {"property_type": "castle"},
    ],
)
def test_valuation_rejects_invalid_input(client, override):
    response = client.post("/v1/valuations", json={**VALID_BODY, **override})

    assert response.status_code == 422


def test_openapi_documents_the_valuation_endpoint(client):
    assert "/v1/valuations" in client.get("/openapi.json").json()["paths"]


def test_valuation_requires_an_api_key(client, session_factory):
    seed_listings(session_factory)

    response = client.post("/v1/valuations", json=VALID_BODY, headers={"X-API-Key": ""})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"


def test_valuation_rejects_an_unknown_api_key(client, session_factory):
    seed_listings(session_factory)

    response = client.post("/v1/valuations", json=VALID_BODY, headers={"X-API-Key": "zano_stolen"})

    assert response.status_code == 401


def test_no_configured_keys_means_nobody_gets_in(session_factory):
    app = create_app(settings=ApiSettings(), session_factory=session_factory)
    client = TestClient(app, headers={"X-API-Key": TEST_KEY})

    assert client.post("/v1/valuations", json=VALID_BODY).status_code == 401


def test_parse_api_keys_maps_hash_to_client():
    assert parse_api_keys(" zetaprop:abc , other:def ") == {"abc": "zetaprop", "def": "other"}
    assert parse_api_keys("") == {}
    assert parse_api_keys(None) == {}


def test_parse_api_keys_rejects_malformed_entries():
    with pytest.raises(ValueError):
        parse_api_keys("zetaprop-without-hash")


def test_generated_keys_are_unique_and_verifiable():
    key_a, hash_a = generate_api_key()
    key_b, _ = generate_api_key()

    assert key_a != key_b
    assert key_a.startswith("zano_")
    assert hash_api_key(key_a) == hash_a


def test_openapi_declares_the_api_key_security_scheme(client):
    schema = client.get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert schema["paths"]["/v1/valuations"]["post"]["security"] == [{"APIKeyHeader": []}]
