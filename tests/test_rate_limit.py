from fastapi.testclient import TestClient

from api.keys import hash_api_key
from api.main import create_app
from api.rate_limit import SlidingWindowRateLimiter
from api.settings import ApiSettings
from tests.test_api import VALID_BODY, seed_listings


class FakeClock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def test_allows_up_to_the_limit_then_blocks():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=FakeClock())

    first, second, third = limiter.hit("a"), limiter.hit("a"), limiter.hit("a")

    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert not third.allowed
    assert third.retry_after_seconds == 60


def test_window_slides_as_time_passes():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)
    limiter.hit("a")
    clock.now += 30
    limiter.hit("a")

    clock.now += 31  # the first hit is now older than the window
    assert limiter.hit("a").allowed

    blocked = limiter.hit("a")
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 29  # until the second hit expires


def test_limits_are_per_key():
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60, clock=FakeClock())
    limiter.hit("a")

    assert not limiter.hit("a").allowed
    assert limiter.hit("b").allowed


def test_api_returns_429_with_retry_after_when_a_client_exceeds_its_limit(session_factory):
    seed_listings(session_factory)
    settings = ApiSettings(
        api_keys={hash_api_key("key-a"): "zetaprop", hash_api_key("key-b"): "other"},
        rate_limit_per_minute=2,
    )
    app = create_app(settings=settings, session_factory=session_factory, clock=FakeClock())
    client = TestClient(app)
    as_a = {"X-API-Key": "key-a"}

    ok = client.post("/v1/valuations", json=VALID_BODY, headers=as_a)
    client.post("/v1/valuations", json=VALID_BODY, headers=as_a)
    blocked = client.post("/v1/valuations", json=VALID_BODY, headers=as_a)
    other_client = client.post("/v1/valuations", json=VALID_BODY, headers={"X-API-Key": "key-b"})

    assert ok.status_code == 200
    assert ok.headers["X-RateLimit-Limit"] == "2"
    assert ok.headers["X-RateLimit-Remaining"] == "1"
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.json()["detail"]["code"] == "rate_limit_exceeded"
    assert other_client.status_code == 200
