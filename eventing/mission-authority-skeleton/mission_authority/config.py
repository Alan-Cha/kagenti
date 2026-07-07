"""Configuration for Mission Authority service."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Mission Authority settings.

    All settings can be overridden via environment variables with the
    MISSION_AUTHORITY_ prefix, e.g., MISSION_AUTHORITY_LOG_LEVEL=DEBUG
    """

    model_config = SettingsConfigDict(
        env_prefix="MISSION_AUTHORITY_",
        env_file=".env",
        case_sensitive=False,
    )

    # Service
    service_name: str = "mission-authority"
    log_level: str = "INFO"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://localhost/missions",
        description="PostgreSQL connection URL (asyncpg driver required)",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Token lifetimes
    mission_token_ttl_hours: int = 24
    access_token_ttl_minutes: int = 15

    # Mission token signing (RS256)
    # In production: mount a PEM secret and set this path.
    # In dev/standalone: a keypair is auto-generated in memory on startup.
    mission_token_private_key_path: str = Field(
        default="",
        description="Path to PEM-encoded RSA private key. Auto-generated in memory if empty.",
    )
    jwt_issuer: str = "https://mission-authority.kagenti.svc.cluster.local"

    # Keycloak
    keycloak_enabled: bool = Field(
        default=False,
        description="Enable Keycloak auth. False = standalone/test mode (stub identities).",
    )
    keycloak_url: str = Field(
        default="http://keycloak.keycloak.svc.cluster.local:8080",
        description="Keycloak base URL",
    )
    keycloak_realm: str = Field(default="kagenti", description="Keycloak realm")
    keycloak_client_id: str = Field(
        default="mission-authority",
        description="Mission Authority's Keycloak client ID",
    )
    keycloak_client_secret: str = Field(
        default="",
        description="Mission Authority's Keycloak client secret (from setup_keycloak.py)",
    )

    @property
    def keycloak_token_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"

    @property
    def keycloak_jwks_url(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    # CORS
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://kagenti-ui.localtest.me:8080",
    ]


settings = Settings()
