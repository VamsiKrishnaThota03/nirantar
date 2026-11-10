"""Runtime configuration for Nirantar.

Security posture (see SECURITY.md):

* ``HOST`` defaults to ``127.0.0.1``. A wildcard bind is never the default;
  a container platform that terminates TLS in front of us sets ``HOST``
  explicitly in its own deployment config.
* ``DEMO_MODE`` defaults to true and serves only generated, fictional
  records. Turning it off means the process expects to handle real
  person-level health data, so it refuses to start unless a real identity
  provider is configured. Fail closed, always.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when the process is asked to run in an unsafe or unreadable
    configuration."""


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        # A mistyped environment variable should name itself, not surface as
        # an anonymous ValueError from deep inside a dataclass default.
        raise ConfigError(
            f"{name}={raw!r} is not a whole number. Refusing to start on a "
            f"configuration value this process cannot interpret."
        ) from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(
            f"{name}={raw!r} is not a number. Refusing to start on a "
            f"configuration value this process cannot interpret."
        ) from exc


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass
class Settings:
    # --- network -----------------------------------------------------------
    # Loopback by default. Deliberate: a bare `0.0.0.0` default is how
    # development servers end up reachable from hostile networks.
    host: str = field(default_factory=lambda: os.environ.get("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    # Browser origins allowed to call the API. Loopback dev origins only by
    # default; a real deployment names its own origin.
    cors_origins: list[str] = field(
        default_factory=lambda: _csv(
            "CORS_ORIGINS", ["http://127.0.0.1:5173", "http://localhost:5173"]
        )
    )

    # --- data mode ---------------------------------------------------------
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", True))
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("DB_PATH", "./var/nirantar.sqlite3"))
    )
    seed: int = field(default_factory=lambda: _int("DATA_SEED", 20260815))

    # --- identity provider (OIDC) -----------------------------------------
    # Nirantar does not mint its own credentials. It verifies tokens issued
    # by whichever OIDC provider the deploying organisation already uses
    # (a state health department's SSO, Keycloak, Auth0, Entra ID, ...).
    oidc_issuer: str | None = field(default_factory=lambda: os.environ.get("OIDC_ISSUER"))
    oidc_audience: str | None = field(default_factory=lambda: os.environ.get("OIDC_AUDIENCE"))
    oidc_jwks_url: str | None = field(default_factory=lambda: os.environ.get("OIDC_JWKS_URL"))
    # Claim that carries role strings, and the role required to act on
    # person-level records.
    oidc_roles_claim: str = field(
        default_factory=lambda: os.environ.get("OIDC_ROLES_CLAIM", "roles")
    )

    # Purpose-named test escape hatch. Defaults to deny. Never keyed off an
    # ambient variable like ENV/NODE_ENV, so it cannot be switched on by
    # accident in a real deployment.
    auth_test_bypass: bool = field(
        default_factory=lambda: _bool("NIRANTAR_AUTH_TEST_BYPASS", False)
    )

    # --- agent brain -------------------------------------------------------
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    )
    llm_timeout_s: float = field(
        default_factory=lambda: _float("LLM_TIMEOUT_S", 45.0)
    )
    # Hard ceiling on spend during a public demo.
    llm_max_calls_per_hour: int = field(
        default_factory=lambda: _int("LLM_MAX_CALLS_PER_HOUR", 400)
    )

    # --- impact ledger -----------------------------------------------------
    ledger_key_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("LEDGER_KEY_PATH", "./var/ledger_signing_key.pem")
        )
    )

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    def jwks_uri(self) -> str | None:
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        if self.oidc_issuer:
            return self.oidc_issuer.rstrip("/") + "/.well-known/jwks.json"
        return None

    def validate(self) -> None:
        """Refuse unsafe combinations at startup rather than at first request."""
        if not self.demo_mode and not self.oidc_configured:
            raise ConfigError(
                "DEMO_MODE=false means this process expects real person-level "
                "health records, but no identity provider is configured. Set "
                "OIDC_ISSUER and OIDC_AUDIENCE (and OIDC_JWKS_URL if your "
                "provider does not publish the standard discovery path), or "
                "leave DEMO_MODE=true to run on generated data. Refusing to "
                "start: an ungated health-records API is not a thing we ship."
            )
        if self.auth_test_bypass and not self.demo_mode:
            raise ConfigError(
                "NIRANTAR_AUTH_TEST_BYPASS is set while DEMO_MODE=false. The "
                "test bypass must never be enabled on a process handling real "
                "records. Refusing to start."
            )
        if self.host not in {"127.0.0.1", "::1", "localhost"}:
            # Not an error: a container platform legitimately needs a wildcard
            # bind so its own proxy can reach us. We record it loudly so an
            # accidental wildcard bind on a laptop is visible in the logs.
            os.environ.setdefault("NIRANTAR_NONLOOPBACK_BIND_ACK", "1")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.validate()
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
