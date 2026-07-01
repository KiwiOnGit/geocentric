"""Secure storage for provider API keys.

Keys are stored in the OS-native credential store via the `keyring` package
(macOS Keychain / Windows Credential Manager / Linux Secret Service) -- no
plaintext key file is ever written. Environment variables always take
precedence, so scripting/CI/headless usage keeps working without touching
the keyring at all.

`keyring` can fail on headless Linux boxes with no Secret Service daemon
running. Every keyring call here is wrapped so that failure degrades to
"no stored key" with a one-time warning rather than crashing the CLI.
"""

from __future__ import annotations

import os
import sys

SERVICE_NAME = "geocentric-code"

ENV_VAR_BY_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

_warned_backends: set[str] = set()


def _keyring_module():
    try:
        import keyring  # noqa: PLC0415 (lazy import keeps this module importable without the dep)
        import keyring.errors

        return keyring
    except Exception:
        return None


def _warn_once(message: str) -> None:
    if message in _warned_backends:
        return
    _warned_backends.add(message)
    print(f"[geocentric] {message}", file=sys.stderr)


class ApiKeyStore:
    """get/set/delete/list API keys for the supported model providers."""

    def __init__(self, service_name: str = SERVICE_NAME):
        self.service_name = service_name

    def env_var_names(self, provider: str) -> tuple[str, ...]:
        names = ENV_VAR_BY_PROVIDER.get(provider, ())
        if isinstance(names, str):
            return (names,)
        return tuple(names)

    def get_env(self, provider: str) -> str | None:
        for name in self.env_var_names(provider):
            value = os.environ.get(name)
            if value:
                return value
        return None

    def get_stored(self, provider: str) -> str | None:
        keyring = _keyring_module()
        if keyring is None:
            return None
        try:
            return keyring.get_password(self.service_name, provider)
        except Exception as exc:
            _warn_once(f"keyring unavailable ({exc}); relying on environment variables only")
            return None

    def get(self, provider: str) -> str | None:
        """Env var wins over stored key, so scripted/CI usage is always overridable."""
        return self.get_env(provider) or self.get_stored(provider)

    def source(self, provider: str) -> str:
        if self.get_env(provider):
            return "environment variable"
        if self.get_stored(provider):
            return "keyring"
        return "none"

    def set(self, provider: str, value: str) -> None:
        keyring = _keyring_module()
        if keyring is None:
            raise RuntimeError(
                "The 'keyring' package is not installed -- run `pip install keyring` "
                "or set the provider's environment variable instead."
            )
        try:
            keyring.set_password(self.service_name, provider, value)
        except Exception as exc:
            raise RuntimeError(f"Failed to store API key in OS keyring: {exc}") from exc

    def clear(self, provider: str) -> bool:
        keyring = _keyring_module()
        if keyring is None:
            return False
        try:
            keyring.delete_password(self.service_name, provider)
            return True
        except Exception:
            return False

    def configured_providers(self) -> dict[str, str]:
        from .config import PROVIDER_NAMES

        return {name: self.source(name) for name in PROVIDER_NAMES if self.source(name) != "none"}


_default_store: ApiKeyStore | None = None


def default_store() -> ApiKeyStore:
    global _default_store
    if _default_store is None:
        _default_store = ApiKeyStore()
    return _default_store
