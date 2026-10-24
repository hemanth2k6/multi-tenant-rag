"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Multi-Tenant RAG API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://rag_user:rag_pass@localhost:5432/ragdb"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "change-me-in-production"

    GEMINI_API_KEY: str = ""
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
    GEMINI_CHAT_MODEL: str = "gemini-2.0-flash"
    EMBEDDING_DIM: int = 768

    VECTOR_BACKEND: str = "pgvector"
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = ""

    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"


settings = Settings()
