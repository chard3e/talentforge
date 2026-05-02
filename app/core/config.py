from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = "password123"

    # Uygulama
    ENV: str = "development"
    DEBUG: bool = True

    # Diğer servisler
    POSTGRES_HOST: str = "localhost"
    REDIS_HOST: str = "localhost"

@lru_cache()
def get_settings() -> Settings:
    return Settings()