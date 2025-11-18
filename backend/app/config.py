"""
Configuration for backend services.
"""

from pathlib import Path
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


def _get_default_db_path() -> Path:
    """Get default database path relative to project root."""
    # Try to find project root (3 levels up from this file: backend/app/config.py)
    config_file = Path(__file__)
    project_root = config_file.parent.parent.parent
    return project_root / "data" / "forms.sqlite"


class Settings(BaseSettings):
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    openai_model: str = Field(default="gpt-5.1", alias="OPENAI_MODEL")
    anthropic_model: str = Field(default="claude-3-5-sonnet-20241022", alias="ANTHROPIC_MODEL")
    sqlite_path: Path = Field(default_factory=_get_default_db_path, alias="SQLITE_PATH")
    max_changed_rows: int = Field(default=100, alias="MAX_CHANGED_ROWS")

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def convert_path(cls, v):
        """Convert string to Path if needed."""
        if isinstance(v, str):
            return Path(v)
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


