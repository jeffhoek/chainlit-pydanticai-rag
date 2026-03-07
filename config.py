from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Keys (anthropic is optional — not needed by ETL scripts)
    anthropic_api_key: Optional[str] = None
    openai_api_key: str

    # PostgreSQL Configuration
    database_url: Optional[str] = None
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "postgresuser"
    pg_password: str = "postgrespw"
    pg_database: str = "inventory"

    def get_database_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"

    # RAG Configuration
    top_k: int = 5
    llm_model: str = "anthropic:claude-haiku-4-5-20251001"
    system_prompt: str = (
        "You are a helpful assistant. Use the retrieve tool to find relevant "
        "context before answering questions. Answer the user's question helpfully "
        "and concisely based on the retrieved context. If the answer is not in the "
        "context, say you don't have that information."
    )

    # Action Buttons (optional)
    action_buttons: list[str] = []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
