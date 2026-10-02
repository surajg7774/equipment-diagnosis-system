"""Settings: provider selection, secrets, CORS origins, deploy-time paths.

``_env_file=None`` makes every test independent of the developer's real .env file.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.embedding_service import EmbeddingService, OnnxEmbeddingService, create_embedder
from app.services.llm_service import GroqLLMService, OllamaLLMService, create_llm_service

KEY = "gsk_test_secret_key_value_123456"


def make(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


# --- provider selection --------------------------------------------------------------------
def test_defaults_are_local_development_friendly():
    s = make()
    assert s.llm_provider == "ollama"  # no key needed for local dev
    assert s.embedding_backend == "onnx"
    assert s.auto_seed_on_startup is True
    assert s.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_provider_factory_returns_the_matching_adapter():
    assert isinstance(create_llm_service(make()), OllamaLLMService)
    groq = create_llm_service(make(llm_provider="groq", groq_api_key=KEY))
    assert isinstance(groq, GroqLLMService)


def test_provider_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    s = make()
    assert s.llm_provider == "groq" and s.groq_api_key.get_secret_value() == KEY


def test_unknown_provider_is_rejected():
    with pytest.raises(ValidationError):
        make(llm_provider="openai")


# --- Groq key handling -------------------------------------------------------------------------
@pytest.mark.parametrize("bad_key", [None, "", "   "])
def test_groq_provider_without_a_key_fails_fast_at_startup(bad_key):
    with pytest.raises(ValidationError, match="GROQ_API_KEY must be set"):
        make(llm_provider="groq", groq_api_key=bad_key)


def test_ollama_provider_does_not_need_a_key():
    assert make(llm_provider="ollama").groq_api_key is None


def test_the_key_never_appears_in_reprs_or_dumps():
    s = make(llm_provider="groq", groq_api_key=KEY)
    assert KEY not in repr(s) and KEY not in str(s)
    assert KEY not in str(s.model_dump())


def test_groq_client_sends_the_key_as_a_bearer_token():
    service = create_llm_service(make(llm_provider="groq", groq_api_key=f"  {KEY}  "))  # stray spaces trimmed
    assert service._client.headers["authorization"] == f"Bearer {KEY}"
    assert str(service._client.base_url).startswith("https://api.groq.com/openai/v1")


@pytest.mark.parametrize("value, ok", [("low", True), ("MEDIUM", True), ("high", True), ("", True), ("extreme", False)])
def test_groq_reasoning_effort_is_validated(value, ok):
    if ok:
        assert make(groq_reasoning_effort=value).groq_reasoning_effort == value.lower()
    else:
        with pytest.raises(ValidationError):
            make(groq_reasoning_effort=value)


# --- CORS origins --------------------------------------------------------------------------------
def test_allowed_origins_are_parsed_cleanly():
    s = make(allowed_origins=" https://my-app.vercel.app/ ,http://localhost:5173,, https://staging.example.com ")
    assert s.cors_origins == ["https://my-app.vercel.app", "http://localhost:5173", "https://staging.example.com"]


def test_allowed_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://prod.example.com")
    assert make().cors_origins == ["https://prod.example.com"]


# --- deploy-time paths are environment-driven -------------------------------------------------------
def test_storage_paths_are_configurable_by_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/custom.db")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", "/tmp/custom_chroma")
    monkeypatch.setenv("AUTO_SEED_ON_STARTUP", "false")
    s = make()
    assert s.database_url == "sqlite:////tmp/custom.db"
    assert s.chroma_persist_dir == "/tmp/custom_chroma"
    assert s.auto_seed_on_startup is False


# --- embedding backend ---------------------------------------------------------------------------------
def test_embedder_factory():
    assert isinstance(create_embedder("onnx", "ignored"), OnnxEmbeddingService)
    assert isinstance(create_embedder("sentence-transformers", "all-MiniLM-L6-v2"), EmbeddingService)
