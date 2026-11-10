"""The gate has to be a gate.

These tests exist because "we'll add auth later" is how health data leaks.
They assert the two properties that matter: an unconfigured gate rejects
everything, and a process holding real records cannot start without one.
"""

from __future__ import annotations

import pytest

from nirantar import config


def test_operator_routes_fail_closed_without_an_identity_provider(client):
    """No OIDC configured means 503 on gated routes, never 200."""
    response = client.get("/api/operator/whoami")
    assert response.status_code == 503
    detail = response.json()["detail"]
    # The error must tell the operator what to configure, not just fail.
    assert "OIDC_ISSUER" in detail
    assert "fail-closed" in detail


def test_admin_routes_fail_closed_too(client):
    assert client.post("/api/operator/reset-demo").status_code == 503


def test_invented_bearer_token_is_rejected(client, monkeypatch):
    """A token we did not verify is not a credential."""
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.invalid")
    monkeypatch.setenv("OIDC_AUDIENCE", "nirantar")
    config.reset_settings_for_tests()
    response = client.get(
        "/api/operator/whoami", headers={"Authorization": "Bearer not-a-real-token"}
    )
    # Either rejected outright, or unavailable because the JWKS cannot be
    # fetched. Both are closed; 200 would not be.
    assert response.status_code in {401, 503}
    assert response.status_code != 200


def test_missing_bearer_is_rejected_when_provider_configured(client, monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.invalid")
    monkeypatch.setenv("OIDC_AUDIENCE", "nirantar")
    config.reset_settings_for_tests()
    response = client.get("/api/operator/whoami")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_real_data_mode_refuses_to_start_without_auth(monkeypatch):
    """The single most important test in the file.

    If someone points this at a live health record system by flipping one
    environment variable, the process must refuse rather than quietly serve
    person-level data to anonymous callers.
    """
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    config.reset_settings_for_tests()
    with pytest.raises(config.ConfigError) as excinfo:
        config.get_settings()
    assert "identity provider" in str(excinfo.value)


def test_test_bypass_is_refused_outside_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.invalid")
    monkeypatch.setenv("OIDC_AUDIENCE", "nirantar")
    monkeypatch.setenv("NIRANTAR_AUTH_TEST_BYPASS", "true")
    config.reset_settings_for_tests()
    with pytest.raises(config.ConfigError):
        config.get_settings()


def test_test_bypass_is_off_by_default():
    settings = config.get_settings()
    assert settings.auth_test_bypass is False


def test_bind_address_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    config.reset_settings_for_tests()
    assert config.get_settings().host == "127.0.0.1"


def test_cors_is_not_a_wildcard(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    config.reset_settings_for_tests()
    origins = config.get_settings().cors_origins
    assert "*" not in origins
    assert all(origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost") for origin in origins)


def test_public_ledger_routes_are_reachable_anonymously(client):
    """Intentional: an impact record only we can read proves nothing."""
    for path in (
        "/api/ledger/summary",
        "/api/ledger/verify",
        "/api/ledger/public-key",
        "/api/calibration",
        "/api/health",
    ):
        assert client.get(path).status_code == 200, path


def test_aggregate_views_are_anonymous_in_demo_mode_only(client):
    assert client.get("/api/overview").status_code == 200
    body = client.get("/api/overview").json()
    assert body["demo_mode"] is True


# --- configuration robustness ---------------------------------------------


def test_lowercase_log_level_does_not_crash_the_process(monkeypatch):
    """Regression: LOG_LEVEL=info took the whole service down on first deploy.

    ``logging`` accepts only upper-case level names, but every container
    platform's config conventionally uses lower case -- including this
    project's own render.yaml. The result was
    ``ValueError: Unknown level: 'info'`` raised at import time, before a
    single request was served.
    """
    import importlib
    import logging

    for value in ("info", "INFO", "Info", "debug", "warning", " info "):
        monkeypatch.setenv("LOG_LEVEL", value)
        from nirantar import main

        importlib.reload(main)
        assert main._log_level() == value.strip().upper()
        # And it must be a level ``logging`` will actually accept.
        logging.getLogger("probe").setLevel(main._log_level())


def test_an_unrecognisable_log_level_falls_back_instead_of_crashing(monkeypatch):
    import importlib

    monkeypatch.setenv("LOG_LEVEL", "chatty")
    from nirantar import main

    importlib.reload(main)
    assert main._log_level() == "INFO"


def test_a_mistyped_numeric_setting_names_itself(monkeypatch):
    """An anonymous ValueError from a dataclass default is not a diagnosis."""
    monkeypatch.setenv("PORT", "eight thousand")
    config.reset_settings_for_tests()
    with pytest.raises(config.ConfigError) as excinfo:
        config.get_settings()
    assert "PORT" in str(excinfo.value)

    monkeypatch.delenv("PORT")
    monkeypatch.setenv("LLM_TIMEOUT_S", "soon")
    config.reset_settings_for_tests()
    with pytest.raises(config.ConfigError) as excinfo:
        config.get_settings()
    assert "LLM_TIMEOUT_S" in str(excinfo.value)


def test_the_shipped_render_blueprint_env_actually_boots(monkeypatch):
    """Apply render.yaml's own environment and import the app.

    The first deploy failed on a value this project ships itself, so the
    shipped deployment config is now exercised rather than assumed.
    """
    import importlib
    from pathlib import Path

    blueprint = Path(__file__).resolve().parents[2] / "render.yaml"
    if not blueprint.exists():
        pytest.skip("render.yaml not present")
    try:
        import yaml
    except ImportError:
        pytest.skip("pyyaml not installed")

    service = yaml.safe_load(blueprint.read_text())["services"][0]
    for entry in service["envVars"]:
        if "value" in entry:
            monkeypatch.setenv(entry["key"], str(entry["value"]))
    # Keep the database and key out of the blueprint's container paths.
    monkeypatch.setenv("DB_PATH", "/tmp/render-probe.sqlite3")
    monkeypatch.setenv("LEDGER_KEY_PATH", "/tmp/render-probe-key.pem")

    config.reset_settings_for_tests()
    from nirantar import main

    importlib.reload(main)
    assert main.app is not None
    settings = config.get_settings()
    # The blueprint deliberately sets a wildcard bind: Render's own proxy has
    # to reach the container. The application default stays loopback.
    assert settings.host == "0.0.0.0"
    assert settings.demo_mode is True
