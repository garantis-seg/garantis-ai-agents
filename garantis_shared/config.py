"""
Config - Base configuration with Pydantic Settings.

Provides a base configuration class that all services can extend.
Handles environment variable loading with validation.

Usage:
    from garantis_shared.config import BaseServiceConfig

    class MyServiceConfig(BaseServiceConfig):
        api_key: str
        max_retries: int = 3

    config = MyServiceConfig()
    print(config.gcp_project_id)  # From env or default
    print(config.api_key)  # Required, raises if not set
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceConfig(BaseSettings):
    """
    Base configuration for all Garantis services.

    Common settings that all services need, with sensible defaults.
    Services should subclass this and add their own settings.

    Environment variables:
        - GCP_PROJECT_ID: Google Cloud project ID
        - GCP_REGION: Google Cloud region
        - LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)
        - K_SERVICE: Cloud Run service name (auto-set by Cloud Run)
        - K_REVISION: Cloud Run revision (auto-set by Cloud Run)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GCP Configuration
    gcp_project_id: str = "394302633873"
    gcp_region: str = "us-central1"

    # Logging
    log_level: str = "INFO"

    # Cloud Run (auto-populated)
    k_service: Optional[str] = None
    k_revision: Optional[str] = None

    @property
    def is_cloud_run(self) -> bool:
        """Check if running in Cloud Run environment."""
        return bool(self.k_service)

    @property
    def service_name(self) -> str:
        """Get service name from K_SERVICE or class name."""
        return self.k_service or self.__class__.__name__


class DatabaseConfig(BaseSettings):
    """
    Database configuration mixin.

    Add this to your config class to get database settings:

        class MyConfig(BaseServiceConfig, DatabaseConfig):
            pass
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database connection
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "cnpj_database"
    db_user: str = "postgres"
    cloud_sql_password: Optional[str] = None

    # Connection pool
    db_pool_min: int = 1
    db_pool_max: int = 10

    @property
    def database_url(self) -> str:
        """Get database connection URL."""
        password = self.cloud_sql_password or ""
        return f"postgresql://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"


class AIConfig(BaseSettings):
    """
    AI service configuration mixin.

    Add this to your config class to get AI settings:

        class MyConfig(BaseServiceConfig, AIConfig):
            pass
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash-lite"

    # Rate limiting
    gemini_rpm: int = 15  # Requests per minute
    gemini_tpm: int = 1000000  # Tokens per minute
