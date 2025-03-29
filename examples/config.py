import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Manages application settings."""
    # Default to an async SQLite DB for easy setup
    DATABASE_URL: str = "sqlite+aiosqlite:///./default.db"

    # Alembic specific URL (often the same, but can differ)
    # Use a synchronous URL for Alembic operations if needed by driver
    # Example for Postgres: "postgresql+psycopg2://user:pass@host/db"
    # Example for Sync SQLite: "sqlite:///./default.db"
    ALEMBIC_DATABASE_URL: str = "sqlite:///./default.db" # Alembic usually prefers sync

    # Add other settings as needed
    ECHO_SQL: bool = False # Set to True to see SQL queries

    model_config = SettingsConfigDict(
        env_file='.env',       # Load .env file
        env_file_encoding='utf-8',
        extra='ignore'         # Ignore extra fields from env
    )


@lru_cache() # Cache the settings object
def get_settings() -> Settings:
    """Returns the cached settings instance."""
    # Explicitly load from .env if it exists relative to this config file or CWD
    # Note: pydantic-settings usually handles this based on model_config
    # from dotenv import load_dotenv
    # load_dotenv() # Ensure .env is loaded if running scripts directly
    return Settings()

# --- Example .env file content (`.env`) ---
# DATABASE_URL="postgresql+asyncpg://user:password@host:port/dbname"
# ALEMBIC_DATABASE_URL="postgresql+psycopg2://user:password@host:port/dbname" # Sync version for Alembic
# ECHO_SQL=True