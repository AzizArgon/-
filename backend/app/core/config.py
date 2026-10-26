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
    gemini_thinking_level: str = "minimal"  # 3.x Flash cannot switch thinking off fully
    gemini_max_output_tokens: int = 65536
    # Each model has its own free daily quota; used in order when the previous one runs out
    gemini_fallback_models: list[str] = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    # Free tier: 5 requests per minute and ~20 per day per model, so chunks are as big as the answer allows
    gemini_rpm: int = 5
    # 800 rows overflowed the answer of flash-lite (split in halves), 400 fit
    parser_chunk_rows: int = 400
    parser_concurrency: int = 2
    # Fallback provider: Groq free tier for gpt-oss-120b is 30 RPM, 1000 RPD, 8K tokens/min
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_rpm: int = 30
    groq_tpm: int = 8000
    groq_chunk_rows: int = 60
    groq_max_output_tokens: int = 4096
    cbu_rate_url: str = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"
    cbu_fetch: bool = True  # false on the public server: cbu.uz is closed to foreign addresses
    cors_origins: list[str] = ["http://localhost:5173"]

    # Public server only (backend/.env there); 0 or "" = off, as on the laptop
    seller_invite_code: str = ""  # sellers register only with this code; buyers freely
    seller_daily_imports: int = 0  # files, texts and retries per store per day
    server_daily_imports: int = 0  # the same for all stores together
    server_daily_ai_requests: int = 0  # Gemini + Groq requests per day, so strangers can't spend the free quota
    login_max_failures: int = 0  # failed logins per IP per window, then 429
    login_window_minutes: int = 15
    register_per_hour: int = 0  # new accounts per IP per hour


settings = Settings()
