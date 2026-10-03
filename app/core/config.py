"""Application configuration.

Every tunable value lives here and is read from environment variables or a
``.env`` file (see ``.env.example``).  Nothing else in the codebase should
hard-code paths, model names, thresholds or URLs.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings object. Invalid values fail fast at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # unknown env vars are not an error
    )

    # --- General ---------------------------------------------------------
    app_name: str = "ServiceDiagnose AI"
    app_version: str = "1.0.0"
    environment: Literal["development", "testing", "production"] = "development"
    log_level: str = "INFO"

    # --- Relational DB (SQLite in dev). Swap to PostgreSQL by changing only
    # this URL, e.g. postgresql+psycopg://user:pass@host/dbname ---------------
    database_url: str = "sqlite:///./servicediagnose.db"

    # --- Vector store (ChromaDB, persisted on local disk) -----------------
    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_name: str = "equipment_issues"
    knowledge_base_path: Path = Path("data/knowledge_base.json")

    # --- Embeddings (local model, no API key) -----------------------------
    # "onnx": all-MiniLM-L6-v2 via the ONNX runtime that ships with ChromaDB: ~210 MB RAM,
    #         no PyTorch (needed to fit Render's 512 MB instances). Produces vectors identical
    #         to the PyTorch version (cosine similarity 1.00000 in tests).
    # "sentence-transformers": the PyTorch version (~750 MB RAM); needs
    #         `pip install sentence-transformers`. Honours EMBEDDING_MODEL_NAME.
    embedding_backend: Literal["onnx", "sentence-transformers"] = "onnx"
    embedding_model_name: str = "all-MiniLM-L6-v2"  # sentence-transformers backend only

    # --- Diagnosis behaviour ---------------------------------------------
    top_k: int = Field(default=3, ge=1, le=10, description="Similar cases to retrieve")
    # Minimum cosine similarity for the best match to count as a "close match".
    # Below it, the LLM is NOT shown the retrieved cases and diagnoses from
    # general knowledge instead (and the response says so).
    # 0.50 was chosen from measurements with all-MiniLM-L6-v2 on this knowledge
    # base: reworded in-KB issues scored 0.56-0.91, off-topic text 0.04-0.14,
    # and most issues that are not in the KB 0.25-0.52. Re-measure if you change
    # the embedding model or the knowledge base.
    low_confidence_threshold: float = Field(default=0.50, ge=0.0, le=1.0)

    # --- LLM provider ------------------------------------------------------
    # "ollama": local model for development (see README). "groq": hosted, for deployment.
    llm_provider: Literal["ollama", "groq"] = "ollama"

    # --- LLM: Groq (OpenAI-compatible hosted API) ---------------------------
    # Secret: set in the environment / .env, never in code. SecretStr keeps it out of reprs/logs.
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # llama-3.1-70b-versatile and llama-3.3-70b-versatile are not offered on this account's
    # model list; openai/gpt-oss-120b is (checked via GET /models).
    groq_model: str = "openai/gpt-oss-120b"
    # gpt-oss models are "reasoning" models: they spend part of the token budget thinking.
    # "low" keeps answers fast and avoids running out of tokens before the JSON is written.
    # Leave EMPTY for non-reasoning models (they reject the parameter).
    groq_reasoning_effort: str = "low"

    # --- Image analysis (vision-language model) -------------------------------
    # "groq": a vision-capable model on Groq (reuses GROQ_API_KEY / GROQ_BASE_URL).
    # "none": image analysis switched off (POST /diagnose-image answers 503).
    # With "groq" but no key, the server still starts and only the image endpoint is unavailable.
    vision_provider: Literal["groq", "none"] = "groq"
    # The only model on the checked account whose `input_modalities` include "image"
    # (GET https://api.groq.com/openai/v1/models). Free tier: ~7,000 input tokens/minute and an
    # image costs ~2,000, so only about 3 analyses per minute.
    groq_vision_model: str = "qwen/qwen3.8-27b"
    # Empty = do not send the parameter (the model does not "think" by default).
    groq_vision_reasoning_effort: str = ""
    # 0 = as repeatable as the model allows: an inspection should not change its verdict on the
    # same photo between runs (at 0.2 the same photo flipped between medium and high severity).
    vision_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    vision_max_tokens: int = Field(default=1024, gt=0)
    vision_timeout_seconds: float = Field(default=60.0, gt=0)

    # --- LLM: Ollama (local server; see README for install + `ollama pull`) --
    # 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 first and each new
    # connection pays a ~2 s delay before falling back to IPv4.
    ollama_base_url: str = "http://127.0.0.1:11434"
    # llama3.2:3b (~2.0 GB) is the lighter of llama3.2:3b / phi3:mini (~2.2 GB).
    ollama_model: str = "llama3.2:3b"
    # How long Ollama keeps the model in RAM after a request. Loading is slow
    # (can take minutes on a cold start), so we keep it warm between diagnoses.
    ollama_keep_alive: str = "30m"
    # Generous because the FIRST request after the model was unloaded includes
    # loading it from disk; warm requests take a few seconds.
    llm_timeout_seconds: float = Field(default=180.0, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)  # low = consistent answers
    # Cap on generated tokens. 1024 (not 512) because reasoning models count their hidden
    # thinking against it too.
    llm_max_tokens: int = Field(default=1024, gt=0)

    # --- Image upload limits ---------------------------------------------
    max_image_size_bytes: int = Field(default=5 * 1024 * 1024, gt=0)

    # --- Web / deployment -------------------------------------------------
    # Comma-separated browser origins allowed to call this API (CORS). In production set it to
    # the deployed frontend, e.g. https://my-app.vercel.app (no trailing slash needed).
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Hosts with an ephemeral filesystem (Render free tier) lose chroma_db on every restart,
    # so an empty knowledge base is re-seeded from knowledge_base_path at startup.
    auto_seed_on_startup: bool = True

    # --- Abuse protection: per-client rate limit on the AI endpoints ----------------
    # /diagnose and /diagnose-image share one bucket per client (each call spends Groq quota).
    # 0 disables the limiter.
    rate_limit_per_minute: int = Field(default=10, ge=0)
    rate_limit_window_seconds: float = Field(default=60.0, gt=0)
    # How many TRUSTED reverse-proxy entries the X-Forwarded-For header ends with (see
    # app/core/rate_limit.py). 0 = ignore the header (local use). On Render start with 1.
    rate_limit_proxy_hops: int = Field(default=0, ge=0, le=5)

    # --- Iterative diagnosis sessions ----------------------------------------------
    # How many different solutions are offered for one problem before the user is told to
    # escalate to a human technician (each "No" costs one LLM call).
    max_solution_attempts: int = Field(default=4, ge=1, le=10)

    # --- Knowledge-base safeguard: how many confirmations a fix needs before it counts as VERIFIED ----------
    # A user's click is worth 1 and a technician's review 2 (see app/core/confirmation.py), so the default of 2
    # leaves a click-only fix "provisional" and lets a technician verify it. 1 = the old behaviour (anything
    # verifies at once): the kill switch if the safeguard ever gets in the way. 3 = needs a user AND a technician.
    min_confirmations_to_verify: int = Field(default=2, ge=1, le=3)

    # --- Technician access code: a small gate on Verify/Confirm and Correct (see app/core/technician.py) ---
    # Secret: set it in the hosting dashboard / .env, never in code. Unset or blank = the gate is off and those two
    # endpoints stay open, as before (also the kill switch). SecretStr keeps it out of reprs and logs.
    technician_access_code: SecretStr | None = None

    @property
    def cors_origins(self) -> list[str]:
        """ALLOWED_ORIGINS as a clean list ("*" allowed; trailing slashes removed)."""
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @field_validator("technician_access_code", mode="before")
    @classmethod
    def _blank_technician_code_means_off(cls, value: object) -> object:
        """An empty variable (TECHNICIAN_ACCESS_CODE=) means "not configured", and stray spaces are not part of the code."""
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("groq_reasoning_effort")
    @classmethod
    def _check_reasoning_effort(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"", "low", "medium", "high"}:
            raise ValueError("GROQ_REASONING_EFFORT must be low, medium, high or empty")
        return value

    @model_validator(mode="after")
    def _groq_needs_a_key(self) -> "Settings":
        # Fail at startup with a clear message instead of on the first request.
        if self.llm_provider == "groq" and not (self.groq_api_key and self.groq_api_key.get_secret_value().strip()):
            raise ValueError("GROQ_API_KEY must be set when LLM_PROVIDER=groq")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance (the .env file is parsed once)."""
    return Settings()
