"""Deployment concerns: CORS, liveness, and start-up seeding on an empty (ephemeral) filesystem."""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings
from app.db.seed import load_records, seed_if_empty
from tests.conftest import KNOWLEDGE_BASE_PATH, FakeEmbedder, FakeLLMService

FRONTEND = "https://my-app.vercel.app"
EVIL = "https://evil.example.com"


# --- CORS ----------------------------------------------------------------------------------------------
@pytest.fixture
def prod_client():
    """An app configured like production: only the deployed frontend is allowed."""
    app = main_module.create_app(Settings(_env_file=None, allowed_origins=FRONTEND + "/", log_level="WARNING"))
    return TestClient(app)


def test_preflight_from_the_allowed_origin_is_approved(prod_client):
    response = prod_client.options(
        "/api/v1/diagnose",
        headers={
            "Origin": FRONTEND,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_preflight_from_another_origin_is_refused(prod_client):
    response = prod_client.options(
        "/api/v1/diagnose",
        headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_actual_requests_get_cors_headers_only_for_allowed_origins(prod_client):
    ok = prod_client.get("/health/live", headers={"Origin": FRONTEND})
    other = prod_client.get("/health/live", headers={"Origin": EVIL})

    assert ok.headers["access-control-allow-origin"] == FRONTEND
    assert "x-request-id" in ok.headers["access-control-expose-headers"].lower()  # frontend can read it
    assert "access-control-allow-origin" not in other.headers


def test_default_settings_allow_the_local_dev_frontend(client):
    response = client.get("/health/live", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_error_responses_also_carry_cors_headers(client):
    # Otherwise the browser would hide a 422's message behind a generic "CORS error".
    response = client.post(
        "/api/v1/diagnose", json={"description": "short"}, headers={"Origin": "http://localhost:5173"}
    )
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


# --- liveness vs readiness -------------------------------------------------------------------------------
def test_liveness_stays_200_when_the_llm_is_down_but_readiness_does_not(client, fake_llm):
    fake_llm.ready = False

    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/live").status_code == 200
    assert client.get("/health").status_code == 503  # diagnostics still tell the truth


# --- seeding ------------------------------------------------------------------------------------------------
def test_seed_if_empty_seeds_an_empty_store_and_leaves_a_populated_one_alone(seeded_collection, fake_embedder):
    # populated: nothing happens, and the embedder is never even called
    class ExplodingEmbedder:
        def embed(self, texts):
            raise AssertionError("must not re-embed an already seeded store")

    assert seed_if_empty(seeded_collection, ExplodingEmbedder(), KNOWLEDGE_BASE_PATH) is None

    # empty: seeded in full
    seeded_collection.delete(ids=seeded_collection.get()["ids"])
    assert seeded_collection.count() == 0
    report = seed_if_empty(seeded_collection, fake_embedder, KNOWLEDGE_BASE_PATH)
    assert report.total_in_store == len(load_records(KNOWLEDGE_BASE_PATH)) == seeded_collection.count()


class _LoadableFakeEmbedder(FakeEmbedder):
    """The real lifespan calls ``embedder.load()``; the fake needs it too. Counts embed calls."""

    def __init__(self):
        self.embed_calls = 0

    def load(self):
        pass

    def embed(self, texts):
        self.embed_calls += 1
        return super().embed(texts)


def _start_app(tmp_path, monkeypatch, embedder, **settings):
    """Run the REAL startup (lifespan) with storage in tmp_path, configured via Settings."""
    monkeypatch.setattr(main_module, "create_embedder", lambda *a, **k: embedder)
    monkeypatch.setattr(main_module, "create_llm_service", lambda s: FakeLLMService())
    config = Settings(
        _env_file=None,
        environment="testing",
        log_level="WARNING",
        database_url=f"sqlite:///{tmp_path / 'tickets.db'}",
        chroma_persist_dir=str(tmp_path / "chroma"),
        knowledge_base_path=KNOWLEDGE_BASE_PATH,
        **settings,
    )
    return TestClient(main_module.create_app(config))


def test_startup_rebuilds_an_empty_knowledge_base_on_an_ephemeral_filesystem(tmp_path, monkeypatch):
    embedder = _LoadableFakeEmbedder()
    with _start_app(tmp_path, monkeypatch, embedder) as client:  # `with` => lifespan runs
        health = client.get("/health").json()

    assert health["knowledge_base_size"] == len(load_records(KNOWLEDGE_BASE_PATH))  # auto-seeded
    assert health["status"] == "ok"
    assert embedder.embed_calls >= 1
    # storage went where the environment-driven settings said
    assert (tmp_path / "tickets.db").exists() and (tmp_path / "chroma").is_dir()


def test_a_restart_with_surviving_data_does_not_reseed(tmp_path, monkeypatch):
    with _start_app(tmp_path, monkeypatch, _LoadableFakeEmbedder()):
        pass  # first boot seeds

    second = _LoadableFakeEmbedder()
    with _start_app(tmp_path, monkeypatch, second) as client:  # same directories = data survived
        size = client.get("/health").json()["knowledge_base_size"]

    assert size == len(load_records(KNOWLEDGE_BASE_PATH))
    assert second.embed_calls == 0  # nothing re-embedded


def test_auto_seed_can_be_switched_off(tmp_path, monkeypatch):
    with _start_app(tmp_path, monkeypatch, _LoadableFakeEmbedder(), auto_seed_on_startup=False) as client:
        assert client.get("/health").json()["knowledge_base_size"] == 0


def test_a_broken_knowledge_base_file_does_not_stop_the_server_from_starting(tmp_path, monkeypatch):
    bad = tmp_path / "kb.json"
    bad.write_text("{ not json")
    embedder = _LoadableFakeEmbedder()
    monkeypatch.setattr(main_module, "create_embedder", lambda *a, **k: embedder)
    monkeypatch.setattr(main_module, "create_llm_service", lambda s: FakeLLMService())
    config = Settings(
        _env_file=None, log_level="WARNING", database_url=f"sqlite:///{tmp_path / 't.db'}",
        chroma_persist_dir=str(tmp_path / "c"), knowledge_base_path=bad,
    )
    with TestClient(main_module.create_app(config)) as client:
        assert client.get("/health/live").status_code == 200  # up, just unseeded
        assert client.get("/health").json()["knowledge_base_size"] == 0
