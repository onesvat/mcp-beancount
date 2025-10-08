from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field, ValidationError, model_validator, field_validator

from .exceptions import ConfigError

CONFIG_ENV_PREFIX = "MCP_BEANCOUNT_"
DEFAULT_CONFIG_FILENAMES = ("mcp-beancount.toml", ".mcp-beancount.toml")


class AppConfig(BaseModel):
    """Runtime configuration for the MCP Beancount server."""

    ledger_path: Path = Field(description="Path to the root Beancount ledger file.")
    default_currency: str | None = Field(
        default=None,
        description="Default currency to use for valuations when none is supplied.",
    )
    timezone: str = Field(default="UTC", description="Local timezone identifier for date handling.")
    locale: str | None = Field(default=None, description="Locale used when formatting responses.")
    backup_dir: Path | None = Field(
        default=None,
        description="Directory where timestamped ledger backups will be written.",
    )
    backup_retention: int | None = Field(
        default=10,
        ge=0,
        description="Maximum number of backups to keep (0 = unlimited).",
    )
    lock_timeout: float = Field(default=10.0, ge=0.1, description="Seconds to wait for the ledger file lock.")
    dry_run_default: bool = Field(default=False, description="Whether tools should default to dry-run mode.")
    http_host: str = Field(default="127.0.0.1", description="HTTP host for the MCP server.")
    http_port: int = Field(default=8765, ge=1, le=65535, description="HTTP port for the MCP server.")
    http_path: str = Field(default="/mcp", description="HTTP path prefix for the MCP transport.")
    enable_nl: bool = Field(default=True, description="Enable the natural-language BeanQuery tool.")

    # Optional Google OAuth authentication for HTTP transports
    google_auth_enabled: bool = Field(
        default=False,
        description="Enable Google OAuth authentication for HTTP endpoints.",
    )
    google_client_id: str | None = Field(
        default=None, description="Google OAuth Client ID (required if auth enabled)."
    )
    google_client_secret: str | None = Field(
        default=None, description="Google OAuth Client Secret (required if auth enabled)."
    )
    google_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL where the server is reachable for OAuth redirects. "
            "Defaults to http://{http_host}:{http_port} if not set."
        ),
    )
    google_required_scopes: list[str] = Field(
        default_factory=lambda: [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        description="OAuth scopes to request from Google.",
    )
    google_redirect_path: str | None = Field(
        default=None,
        description="Optional OAuth redirect path (defaults to provider's /auth/callback).",
    )
    google_allowed_emails: list[str] = Field(
        default_factory=list,
        description="Comma- or list-defined email allowlist. Empty list means allow all authenticated users.",
    )

    @field_validator("google_allowed_emails", mode="before")
    @staticmethod
    def _parse_allowed_emails(value: Any) -> list[str] | Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.replace(" ", ",").split(",") if part.strip()]
        return value

    model_config = {"validate_assignment": True}

    @model_validator(mode="after")
    def _normalise_paths(self) -> "AppConfig":
        ledger_path = self.ledger_path.expanduser().resolve()
        if not ledger_path.exists():
            raise ConfigError(f"Configured ledger file does not exist: {ledger_path}")
        if not ledger_path.is_file():
            raise ConfigError(f"Configured ledger path is not a file: {ledger_path}")

        backup_dir = self.backup_dir or ledger_path.parent / ".backups"
        object.__setattr__(self, "ledger_path", ledger_path)
        object.__setattr__(self, "backup_dir", backup_dir.expanduser().resolve())

        # If Google auth is enabled, ensure required fields are present and set defaults.
        if self.google_auth_enabled:
            if not self.google_client_id or not self.google_client_secret:
                raise ConfigError(
                    "Google auth enabled but google_client_id/google_client_secret are not configured."
                )
            if not self.google_base_url:
                object.__setattr__(
                    self,
                    "google_base_url",
                    f"http://{self.http_host}:{self.http_port}",
                )
            normalized = [email.strip().lower() for email in self.google_allowed_emails if email.strip()]
            object.__setattr__(self, "google_allowed_emails", normalized)
        return self


def _load_toml_config(path: Path) -> dict[str, Any]:
    import tomllib

    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(
    explicit_path: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load configuration from a file and environment variables."""

    env = dict(env or os.environ)
    config_path: Path | None = None

    if explicit_path:
        config_candidate = Path(explicit_path).expanduser()
        if not config_candidate.exists():
            raise ConfigError(f"Configuration file not found: {config_candidate}")
        config_path = config_candidate
    else:
        env_path = env.get(f"{CONFIG_ENV_PREFIX}CONFIG")
        if env_path:
            candidate = Path(env_path).expanduser()
            if not candidate.exists():
                raise ConfigError(f"Environment-selected config file not found: {candidate}")
            config_path = candidate
        else:
            for filename in DEFAULT_CONFIG_FILENAMES:
                candidate = Path(filename).expanduser()
                if candidate.exists():
                    config_path = candidate
                    break

    file_data: dict[str, Any] = {}
    if config_path:
        file_data = _load_toml_config(config_path)

    config_data: dict[str, Any] = {}
    config_data.update(file_data)

    # Apply environment overrides.
    env_mapping = {
        "LEDGER": "ledger_path",
        "LEDGER_PATH": "ledger_path",
        "DEFAULT_CURRENCY": "default_currency",
        "TIMEZONE": "timezone",
        "LOCALE": "locale",
        "BACKUP_DIR": "backup_dir",
        "BACKUP_RETENTION": "backup_retention",
        "LOCK_TIMEOUT": "lock_timeout",
        "DRY_RUN_DEFAULT": "dry_run_default",
        "HTTP_HOST": "http_host",
        "HTTP_PORT": "http_port",
        "HTTP_PATH": "http_path",
        "ENABLE_NL": "enable_nl",
        # Google OAuth
        "GOOGLE_AUTH_ENABLED": "google_auth_enabled",
        "GOOGLE_CLIENT_ID": "google_client_id",
        "GOOGLE_CLIENT_SECRET": "google_client_secret",
        "GOOGLE_BASE_URL": "google_base_url",
        "GOOGLE_REQUIRED_SCOPES": "google_required_scopes",
        "GOOGLE_REDIRECT_PATH": "google_redirect_path",
        "GOOGLE_ALLOWED_EMAILS": "google_allowed_emails",
    }

    for env_key, field_name in env_mapping.items():
        value = env.get(f"{CONFIG_ENV_PREFIX}{env_key}")
        if value is not None:
            if field_name in {"lock_timeout"}:
                config_data[field_name] = float(value)
            elif field_name in {"http_port", "backup_retention"}:
                config_data[field_name] = int(value)
            elif field_name in {"dry_run_default", "enable_nl", "google_auth_enabled"}:
                config_data[field_name] = value.lower() in {"1", "true", "yes", "on"}
            elif field_name in {"google_required_scopes"}:
                # Comma or space separated list
                scopes = [s.strip() for s in value.replace(" ", ",").split(",") if s.strip()]
                config_data[field_name] = scopes
            elif field_name in {"google_allowed_emails"}:
                emails = [s.strip() for s in value.replace(" ", ",").split(",") if s.strip()]
                config_data[field_name] = emails
            else:
                config_data[field_name] = value

    if "ledger_path" not in config_data:
        raise ConfigError(
            "Ledger path must be configured via config file or "
            f"{CONFIG_ENV_PREFIX}LEDGER(_PATH) environment variable."
        )

    try:
        return AppConfig(**config_data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
