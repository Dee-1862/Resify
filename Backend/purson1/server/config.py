"""
CiteSafe Configuration
======================
All settings loaded from environment / .env file via pydantic-settings.
"""

import os
from pydantic import model_validator
from pydantic_settings import BaseSettings

# Resolve paths relative to this file so they work regardless of cwd
_here = os.path.dirname(os.path.abspath(__file__))
_env_file = os.path.join(_here, "..", ".env")
_default_cache_db = os.path.join(_here, "..", "cache.db")


class Settings(BaseSettings):
    # --- API Keys ---
    GEMINI_API_KEY: str = ""
    S2_API_KEY: str = ""              # Semantic Scholar (optional, raises rate limits)

    # --- LLM ---
    LLM_MODEL: str = "gemini-2.0-flash"
    LLM_TEMPERATURE: float = 0.1
    TOKEN_BUDGET_DEFAULT: int = 100_000

    # --- Embedding ---
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # --- Verification thresholds ---
    EMBEDDING_SUPPORT_THRESHOLD: float = 0.75
    EMBEDDING_CONTRADICT_THRESHOLD: float = 0.75
    EMBEDDING_MARGIN_THRESHOLD: float = 0.2

    # --- Cache ---
    CACHE_DB_PATH: str = _default_cache_db
    SOURCE_CACHE_TTL_DAYS: int = 30
    VERIFICATION_CACHE_TTL_DAYS: int = 7
    PAPER_CACHE_TTL_HOURS: int = 24

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    RATE_LIMIT: str = "20/hour"

    # --- Compression ---
    USE_CVP: bool = True
    USE_FINGERPRINTS: bool = True

    # --- Agent timeouts ---
    AGENT_TIMEOUT_SECONDS: float = 500.0

    @model_validator(mode="after")
    def _resolve_relative_paths(self):
        if not os.path.isabs(self.CACHE_DB_PATH):
            self.CACHE_DB_PATH = os.path.join(_here, "..", self.CACHE_DB_PATH)
        return self

    model_config = {"env_file": _env_file, "env_file_encoding": "utf-8"}


settings = Settings()
