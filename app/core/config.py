from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI PM Learning Copilot"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    storage_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/app.db"
    chroma_path: Path = Path("./data/chroma")

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = Field(default="", repr=False)
    llm_chat_model: str = "gpt-4.1-mini"
    llm_embedding_model: str = "text-embedding-3-small"
    concept_query_cache_ttl_days: int = Field(default=14, ge=1, le=90)
    max_new_concept_api_queries_per_day: int = Field(default=20, ge=1, le=1000)



@lru_cache
def get_settings() -> Settings:
    return Settings()
