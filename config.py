from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys
    anthropic_api_key: str
    openai_api_key: str

    # AWS Credentials
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str = "us-east-1"

    # S3 Configuration
    s3_bucket: str
    s3_key: str

    # RAG Configuration
    top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 50

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
