from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Every test gets a throwaway database, ledger key and clean settings."""
    tmp = Path(tempfile.mkdtemp(prefix="nirantar-test-"))
    monkeypatch.setenv("DB_PATH", str(tmp / "test.sqlite3"))
    monkeypatch.setenv("LEDGER_KEY_PATH", str(tmp / "key.pem"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DATA_SEED", "20260815")
    # Tests never spend tokens. The deterministic core is what is under test.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    monkeypatch.delenv("NIRANTAR_AUTH_TEST_BYPASS", raising=False)

    from nirantar import config, state

    config.reset_settings_for_tests()
    state.reset_state_for_tests()
    yield tmp
    state.reset_state_for_tests()
    config.reset_settings_for_tests()


@pytest.fixture
def app_state():
    from nirantar.state import get_state

    return get_state()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from nirantar.main import app

    with TestClient(app) as test_client:
        yield test_client
