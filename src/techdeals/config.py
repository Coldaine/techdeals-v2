from __future__ import annotations

from pydantic_settings import BaseSettings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    neon_database_url: str
    openrouter_api_key: str = ""
    kilo_gateway_api: str = ""
    kilo_code_api_key: str = ""
    llm_model: str = "google/gemini-2.5-flash"
    llm_batch_size: int = 20
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def llm_base_url(self) -> str:
        """Return the LLM API base URL.

        Prefers Kilo gateway if configured, falls back to OpenRouter.
        """
        if self.kilo_gateway_api:
            return self.kilo_gateway_api
        return OPENROUTER_BASE_URL

    @property
    def llm_api_key(self) -> str:
        """Return the LLM API key.

        Prefers Kilo gateway key if configured, falls back to OpenRouter key.
        """
        if self.kilo_gateway_api and self.kilo_code_api_key:
            return self.kilo_code_api_key
        return self.openrouter_api_key


def get_settings() -> Settings:
    return Settings()
