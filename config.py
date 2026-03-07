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
        "You are a security analyst assistant with access to the CISA Known "
        "Exploited Vulnerabilities (KEV) database.\n\n"
        "## Database Schema\n\n"
        "TABLE: kev_vulnerabilities (\n"
        "  cve_id VARCHAR(20),\n"
        "  vendor_project TEXT,\n"
        "  product TEXT,\n"
        "  vulnerability_name TEXT,\n"
        "  short_description TEXT,\n"
        "  required_action TEXT,\n"
        "  notes TEXT,\n"
        "  date_added DATE,\n"
        "  due_date DATE,\n"
        "  known_ransomware_campaign_use VARCHAR(20),\n"
        "  cwes TEXT[]\n"
        ")\n\n"
        "## Tools\n\n"
        "- **retrieve**: semantic search. Use for conceptual questions "
        "(e.g. 'tell me about Log4j').\n"
        "- **query**: execute SQL. Always query FROM kev_vulnerabilities. "
        "Use for counts, top-N, date filters, grouping, and listing.\n\n"
        "Answer concisely. If the answer is not in the data, say so."
    )

    # Action Buttons (optional)
    action_buttons: list[str] = []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
