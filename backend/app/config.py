from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_name: str = "Grounded Case AI"
    version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@postgres:5432/caseai"
    )

    # OpenAI — not used in Step 1, but declared so config is complete
    openai_api_key: str = ""
    model_primary: str = "gpt-4.1"
    model_cheap: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    # MinIO — canonical blob storage for uploaded documents.
    # Two endpoints because the backend talks to MinIO over the compose
    # network, but presigned URLs are handed to the USER's browser and
    # must embed a hostname the browser can resolve.
    minio_internal_endpoint: str = "minio:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "documents"
    minio_secure: bool = False


settings = Settings()
