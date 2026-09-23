from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# All three apps share the repo-root .env.
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    # Server-side refusal fallbacks. Set to empty to disable, e.g. for a
    # model that does not support them.
    anthropic_fallbacks: str = "default"
    agent_mock_llm: bool = False
    agent_port: int = 8000
    sync_http_url: str = "http://localhost:1234"
    web_origin: str = "http://localhost:5173"


settings = Settings()
