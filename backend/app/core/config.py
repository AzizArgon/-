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
    # 3.8-flash answered in 50-150 s per request in Oct 2026, 3.5-flash in ~2 s
    gemini_model: str = "gemini-3.5-flash"
    gemini_thinking_level: str = "low"
    # Each model has its own free daily quota; used in order when the previous one runs out
    gemini_fallback_models: list[str] = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    # Free tier allows only 5 requests per minute, so chunks are big and requests are throttled
    parser_chunk_rows: int = 250
    parser_concurrency: int = 3
    gemini_rpm: int = 5
    cbu_rate_url: str = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
