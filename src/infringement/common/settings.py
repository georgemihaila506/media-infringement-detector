from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment (or .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://infringement:infringement@localhost:5432/infringement"
    aws_region: str = "eu-central-1"
    s3_bucket: str = "infringement"
    sqs_tasks_queue: str = "activity-tasks"
    sqs_results_queue: str = "activity-results"


@lru_cache
def get_settings() -> Settings:
    return Settings()
