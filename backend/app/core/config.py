from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_name: str = "pc_market"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    database_url: str = f"sqlite:///{BACKEND_DIR / 'database.db'}"
    gemini_api_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
