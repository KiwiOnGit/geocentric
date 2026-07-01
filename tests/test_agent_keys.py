import pytest

from geocentric.agent.keys import ApiKeyStore


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_env_var_takes_precedence_over_stored_key(monkeypatch):
    store = ApiKeyStore()
    monkeypatch.setattr(store, "get_stored", lambda provider: "stored-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-value")
    assert store.get("anthropic") == "env-value"
    assert store.source("anthropic") == "environment variable"


def test_falls_back_to_stored_key_when_no_env_var(monkeypatch):
    store = ApiKeyStore()
    monkeypatch.setattr(store, "get_stored", lambda provider: "stored-value")
    assert store.get("anthropic") == "stored-value"
    assert store.source("anthropic") == "keyring"


def test_no_key_configured_reports_none(monkeypatch):
    store = ApiKeyStore()
    monkeypatch.setattr(store, "get_stored", lambda provider: None)
    assert store.get("anthropic") is None
    assert store.source("anthropic") == "none"


def test_keyring_failure_degrades_gracefully(monkeypatch):
    store = ApiKeyStore()

    def _boom():
        raise RuntimeError("no secret service running")

    monkeypatch.setattr("geocentric.agent.keys._keyring_module", lambda: None)
    # get_stored should return None, not raise, when the keyring backend is unavailable.
    assert store.get_stored("anthropic") is None
    assert store.get("anthropic") is None


def test_gemini_checks_both_env_var_names(monkeypatch):
    store = ApiKeyStore()
    monkeypatch.setenv("GOOGLE_API_KEY", "google-value")
    assert store.get_env("gemini") == "google-value"
