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
    llm_model: str = "anthropic:claude-haiku-4-5-20251001"
    system_prompt: str = (
        "You are a helpful assistant. Use the retrieve tool to find relevant "
        "context before answering questions. Answer the user's question helpfully "
        "and concisely based on the retrieved context. If the answer is not in the "
        "context, say you don't have that information."
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
