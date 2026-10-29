from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env"), env_prefix="ATRIUM_", extra="ignore")

    database_url: str = "postgresql+psycopg://atrium:atrium@127.0.0.1:55432/atrium"
    base_url: str = "http://localhost:8000"
    cookie_secure: bool = False
    session_days: int = 14

    data_dir: Path = ROOT / "data"
    agents_dir: Path = ROOT / "agents"
    frontend_dist: Path = ROOT / "frontend" / "dist"

    # LLM: anthropic | openai_compat | fake
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str = ""
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    openai_compat_model: str = ""
    # Sent as reasoning_effort, e.g. "none" to switch off slow thinking on local models. Empty = not sent.
    openai_compat_reasoning: str = ""

    # Voice
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Notes transcription: faster-whisper model name, or "fake" for tests
    whisper_model: str = "small"
    whisper_language: str = ""

    guest_link_days: int = 90
    max_upload_mb: int = 20

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
