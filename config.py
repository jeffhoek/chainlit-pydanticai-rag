from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys
    anthropic_api_key: str
    openai_api_key: str

    # AWS Credentials (optional — only needed when using S3)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"

    # S3 Configuration (optional — falls back to local data/ dir if unset)
    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None

    # Local fallback
    data_path: str = "data"

    # RAG Configuration
    top_k: int = 5
    llm_model: str = "anthropic:claude-haiku-4-5-20251001"
    system_prompt: str = (
        "You are a helpful assistant. Use the retrieve tool to find relevant "
        "context before answering questions. Answer the user's question helpfully "
        "and concisely based on the retrieved context. If the answer is not in the "
        "context, say you don't have that information."
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
