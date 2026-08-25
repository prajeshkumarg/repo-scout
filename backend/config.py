"""Application configuration. Every value comes from the environment."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Settings loaded from the environment, then .env files.

    Both locations are read: the repo root (documented in the README) and
    backend/ (where the processes actually run from). Later files win.
    """

    model_config = SettingsConfigDict(
        env_file=(
            REPO_ROOT / ".env",
            Path(__file__).parent / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://scout:scout@localhost:5432/repo_scout"
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Browser origins allowed to call the API. Empty in development,
    # where the LAN patterns below cover it; set to the deployed web
    # address in production, comma-separated if there is more than one.
    allowed_origins: str = ""

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # pgvector column width, set by the embedding model. Must stay <= 2000:
    # pgvector refuses to build an HNSW/IVFFlat index above that.
    embedding_dim: int = 384

    # Local embedding via fastembed. The model is downloaded on first use
    # and cached. bge-small-en-v1.5 (33M params, 384 dims) is the small,
    # CPU-friendly default: the fp32 BERT-size models take ~an hour to
    # index one mid-size repo on a laptop. M2 evals decide whether a
    # bigger model's recall is worth the cost.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embed_batch_size: int = 100

    # The agent's LLM (deep mode). Chat quota is separate from the
    # embedding quota; GOOGLE_API_KEY lives in the env/.env files.
    # The lite model is the free-tier default: gemini-3.5-flash allows
    # only 20 requests per DAY on the free tier, which cannot run a
    # 60-question eval (~180 requests). Lite handles tool calls and
    # thought signatures the same way.
    google_api_key: str | None = None
    google_agent_model: str = "gemini-3.5-flash-lite"

    # Chunk budget in characters (a cheap proxy for tokens: chars / 4).
    # 6000 chars ~= 1500 tokens, under gemini-embedding-001's 2048-token
    # input cap so the chunker, not the API, decides what gets truncated.
    chunk_max_chars: int = 6000


@lru_cache
def get_settings() -> Settings:
    """Cached settings, so the .env file is read once per process."""
    return Settings()
