"""Rate limiter: the algorithm (with a fake clock, no sleeping), client identification, and the API."""

import threading

import pytest
from starlette.requests import Request

from app.core.config import Settings
from app.core.rate_limit import RateLimiter, client_key


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def limiter(clock, limit=3, window=60.0, **kw) -> RateLimiter:
    return RateLimiter(limit, window, clock=clock, **kw)


# --- the algorithm -----------------------------------------------------------------------------------
def test_allows_requests_up_to_the_limit_then_blocks(clock):
    rl = limiter(clock, limit=3)

    results = [rl.check("a") for _ in range(5)]

    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results[:3]] == [2, 1, 0]


def test_the_wait_time_is_how_long_until_the_oldest_request_leaves_the_window(clock):
    rl = limiter(clock, limit=3, window=60)
    for _ in range(3):  # t=0, 10, 20
        rl.check("a")
        clock.advance(10)
    # now t=30; the oldest request (t=0) leaves the window at t=60 => 30 s to wait
    assert rl.check("a").retry_after_seconds == 30
    clock.advance(0.4)
    assert rl.check("a").retry_after_seconds == 30  # 29.6 s rounds UP, never down to a too-early retry


def test_recovers_once_the_window_has_passed(clock):
    rl = limiter(clock, limit=3, window=60)
    for _ in range(3):
        rl.check("a")
    assert not rl.check("a").allowed

    clock.advance(59)
    assert not rl.check("a").allowed  # still inside the window
    clock.advance(1.01)
    assert rl.check("a").allowed  # the first requests have expired


def test_it_is_a_sliding_window_slots_free_up_one_at_a_time(clock):
    rl = limiter(clock, limit=3, window=60)
    for _ in range(3):  # t=0, 10, 20
        rl.check("a")
        clock.advance(10)
    clock.advance(30.5)  # t=60.5: only the t=0 request has expired

    assert rl.check("a").allowed  # one slot is back...
    assert not rl.check("a").allowed  # ...but not two (the t=10 and t=20 requests still count)
    clock.advance(10)  # t=70.5: the t=10 request has expired
    assert rl.check("a").allowed


def test_refused_requests_do_not_extend_the_block(clock):
    rl = limiter(clock, limit=2, window=60)
    rl.check("a")
    rl.check("a")
    for _ in range(50):  # hammering while blocked...
        clock.advance(1)
        assert not rl.check("a").allowed
    clock.advance(10.5)  # ...t=60.5 after the FIRST request

    assert rl.check("a").allowed  # recovers on schedule, hammering did not push it back


def test_clients_are_limited_independently(clock):
    rl = limiter(clock, limit=2)
    for _ in range(2):
        rl.check("alice")

    assert not rl.check("alice").allowed
    assert rl.check("bob").allowed  # someone else is unaffected


def test_a_limit_of_zero_disables_limiting(clock):
    rl = limiter(clock, limit=0)
    assert all(rl.check("a").allowed for _ in range(1000))


def test_memory_stays_bounded_even_if_an_attacker_invents_endless_client_keys(clock):
    rl = limiter(clock, limit=3, max_keys=50)

    for i in range(5000):
        rl.check(f"10.0.{i // 250}.{i % 250}")

    assert len(rl._hits) <= 50


def test_idle_clients_are_evicted_before_active_ones(clock):
    rl = limiter(clock, limit=3, window=60, max_keys=3)
    for key in ("old1", "old2"):
        rl.check(key)
    clock.advance(120)  # old1/old2 are now idle
    for key in ("busy1", "busy2"):
        rl.check(key)

    assert "busy1" in rl._hits and "busy2" in rl._hits  # the active ones survived the clean-up


def test_concurrent_requests_cannot_slip_past_the_limit():
    rl = RateLimiter(10, 60)  # real clock
    allowed = []

    def hit():
        allowed.append(rl.check("same-client").allowed)

    threads = [threading.Thread(target=hit) for _ in range(100)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert allowed.count(True) == 10  # exactly the limit, even with 100 threads racing


# --- who is the client? --------------------------------------------------------------------------------------
def make_request(xff: str | None = None, peer: str | None = "10.0.0.1") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    scope = {"type": "http", "headers": headers, "client": (peer, 5000) if peer else None}
    return Request(scope)


def test_by_default_the_forwarded_header_is_ignored_so_it_cannot_be_spoofed():
    assert client_key(make_request(xff="6.6.6.6"), proxy_hops=0) == "10.0.0.1"


@pytest.mark.parametrize(
    "xff, hops, expected",
    [
        ("1.1.1.1", 1, "1.1.1.1"),
        ("6.6.6.6, 1.1.1.1", 1, "1.1.1.1"),  # a forged leftmost entry is ignored: we read from the right
        ("6.6.6.6, 1.1.1.1, 172.16.0.5", 2, "1.1.1.1"),  # two trusted proxies appended after the client
        ("  6.6.6.6 ,  1.1.1.1 ", 1, "1.1.1.1"),
    ],
)
def test_the_client_is_read_from_the_right_hand_end_of_the_forwarded_header(xff, hops, expected):
    assert client_key(make_request(xff=xff), proxy_hops=hops) == expected


@pytest.mark.parametrize("xff, hops", [(None, 1), ("", 1), ("1.1.1.1", 2)])
def test_a_missing_or_too_short_header_falls_back_to_the_connection_address(xff, hops):
    assert client_key(make_request(xff=xff), proxy_hops=hops) == "10.0.0.1"


def test_no_connection_info_at_all_is_still_handled():
    assert client_key(make_request(peer=None)) == "unknown"


# --- the API ---------------------------------------------------------------------------------------------------
@pytest.fixture
def limited(app, clock):
    """The shared test app, but with a real 3-per-minute limiter driven by a fake clock."""
    app.state.rate_limiter = RateLimiter(3, 60, clock=clock)
    return app


def post(client, text="pump making loud grinding noise and leaking oil", **headers):
    return client.post("/api/v1/diagnose", json={"description": text}, headers=headers)


def test_default_configuration_is_ten_requests_per_minute_per_client():
    settings = Settings(_env_file=None)
    assert (settings.rate_limit_per_minute, settings.rate_limit_window_seconds, settings.rate_limit_proxy_hops) == (10, 60, 0)


def test_the_request_after_the_limit_gets_a_clean_429(limited, client, fake_llm):
    assert [post(client).status_code for _ in range(3)] == [200, 200, 200]

    response = post(client)

    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["message"] == "Too many requests. Please wait 60 seconds and try again."
    assert response.headers["Retry-After"] == "60"
    assert "Traceback" not in response.text
    assert len(fake_llm.calls) == 3  # the refused request never reached the (billable) LLM


def test_a_refused_request_stores_nothing(limited, client):
    for _ in range(4):
        post(client)

    assert client.get("/api/v1/history").json()["total"] == 3


def test_the_limit_recovers_after_the_window(limited, client, clock):
    for _ in range(3):
        post(client)
    assert post(client).status_code == 429

    clock.advance(30)
    still = post(client)
    assert still.status_code == 429 and still.headers["Retry-After"] == "30"  # the wait counts down

    clock.advance(31)
    assert post(client).status_code == 200


def test_diagnose_and_diagnose_image_share_one_bucket(limited, client, fake_vision):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    post(client)
    post(client)
    assert client.post("/api/v1/diagnose-image", files={"file": ("a.png", png, "image/png")}).status_code == 200

    assert client.post("/api/v1/diagnose-image", files={"file": ("a.png", png, "image/png")}).status_code == 429
    assert post(client).status_code == 429
    assert len(fake_vision.calls) == 1  # the refused upload never reached the vision model


def test_cheap_endpoints_are_never_throttled(limited, client):
    for _ in range(3):
        post(client)
    assert post(client).status_code == 429

    for path in ("/health", "/health/live", "/api/v1/history", "/api/v1/knowledge-base/stats", "/openapi.json"):
        assert client.get(path).status_code == 200, path


def test_invalid_requests_count_too_so_spamming_garbage_is_also_limited(limited, client):
    statuses = [client.post("/api/v1/diagnose", json={"description": "x"}).status_code for _ in range(4)]
    assert statuses == [422, 422, 422, 429]


def test_the_429_is_readable_by_the_browser_app_via_cors(limited, client):
    for _ in range(3):
        post(client)

    response = post(client, Origin="http://localhost:5173")

    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


def test_changing_the_forwarded_header_cannot_dodge_the_limit_by_default(limited, client):
    codes = [post(client, **{"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]  # hops=0: the header is ignored entirely


def test_behind_a_trusted_proxy_each_real_client_gets_its_own_bucket(limited, client):
    limited.state.settings.rate_limit_proxy_hops = 1

    alice = [post(client, **{"X-Forwarded-For": "198.51.100.1"}).status_code for _ in range(4)]
    bob = post(client, **{"X-Forwarded-For": "198.51.100.2"}).status_code

    assert alice == [200, 200, 200, 429]
    assert bob == 200  # a different client is not affected


def test_a_forged_leftmost_entry_does_not_dodge_the_limit_behind_a_proxy(limited, client):
    limited.state.settings.rate_limit_proxy_hops = 1

    codes = [post(client, **{"X-Forwarded-For": f"{i}.{i}.{i}.{i}, 198.51.100.1"}).status_code for i in range(1, 5)]

    assert codes == [200, 200, 200, 429]  # the real client (rightmost) is the same every time


def test_a_rate_limit_rejection_is_logged_with_the_path(limited, client, caplog):
    for _ in range(3):
        post(client)
    with caplog.at_level("WARNING", logger="app.api.deps"):
        post(client)

    record = next(r for r in caplog.records if r.getMessage() == "rate_limited")
    assert record.path == "/api/v1/diagnose" and record.retry_after == 60
