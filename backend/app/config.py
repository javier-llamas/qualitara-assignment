from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fleet"
    redis_url: str = "redis://localhost:6379/0"
    fleet_channel: str = "fleet:events"
    session_ttl_seconds: int = 60 * 60 * 8

    speed_limit_mps: float = 5.0
    low_battery_pct: int = 15
    rapid_battery_drop_pct: int = 10

    sse_keepalive_seconds: float = 20.0
    sse_queue_maxsize: int = 100


settings = Settings()
