# app/settings.py
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "production"] = "development"
    database_url: str = "postgresql+asyncpg://gympro_app:change-me@localhost:5432/gympro"
    test_database_url: str = "postgresql+asyncpg://gympro_app:change-me@localhost:5432/gympro_test"
    seed_database_url: str = "postgresql+asyncpg://gympro_seed:change-me@localhost:5432/gympro"
    test_seed_database_url: str = "postgresql+asyncpg://gympro_seed:change-me@localhost:5432/gympro_test"
    analytics_database_url: str = "postgresql+asyncpg://gympro_analytics:change-me@localhost:5432/gympro"
    superuser_database_url: str = "postgresql+asyncpg://postgres:root@localhost:5432/gympro_test"
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    token_hmac_secret: str = ""
    frontend_url: str = "http://localhost:5173"  # links in emails come from here, never from Host header

    llm_provider: Literal["azure", "openai", "ollama", "fake"] = "fake"
    llm_model: str = "gpt-4o"                    # Azure: deployment name; Ollama: e.g. "qwen2.5:14b-instruct"
    llm_api_key: str = "fake"
    llm_base_url: str | None = "http://localhost:11434/v1"
    azure_endpoint: str | None = None
    azure_api_version: str = "2024-10-21"
    agent_max_tool_steps: int = 6
    agent_timeout_s: float = 25.0
    run_token_budget: int = 20_000
    chroma_path: str = "./gympro_vector_store"

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    smtp_host: str = "localhost"                 # Mailpit default
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from: str = "GymPro <no-reply@gympro.local>"
    payments_mode: Literal["mock", "razorpay", "disabled"] = "mock"
    razorpay_key_id: str | None = None           # public, sent to browser
    razorpay_key_secret: str | None = None       # server only
    razorpay_webhook_secret: str | None = None   # server only

    gym_timezone: str = "Asia/Kolkata"
    booking_buffer_minutes: int = 15
    late_cancel_hours: int = 2
    pending_action_ttl_min: int = 10
    bundle_max_steps: int = 5
    trial_classes: int = 3
    trial_days: int = 14

    def model_post_init(self, __context) -> None:
        if self.env == "production" and self.payments_mode == "mock":
            raise RuntimeError("PAYMENTS_MODE=mock is not allowed when ENV=production")
        if self.env == "production" and self.llm_provider == "fake":
            raise RuntimeError("LLM_PROVIDER=fake is not allowed when ENV=production")

    @property
    def formatted_jwt_private_key(self) -> str:
        return self.jwt_private_key.replace("\\n", "\n")

    @property
    def formatted_jwt_public_key(self) -> str:
        return self.jwt_public_key.replace("\\n", "\n")


settings = Settings()
