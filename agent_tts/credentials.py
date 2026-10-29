"""Provider API keys: Windows Credential Manager first, environment second.

A key entered in the dashboard is stored in the operating system's credential
store (never in voices.yaml, .env, or the repository). An environment variable
(including one loaded from .env) is the fallback, so existing setups keep
working. The saved key wins when both exist because it was entered deliberately
in the app; `lookup` reports the source so the UI can say which one is in use.
"""
import os

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "agent-tts"
SAVED = "saved"
ENVIRONMENT = "environment"


class CredentialError(RuntimeError):
    """The credential store could not be read or written."""


def _saved(env_var: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, env_var) or None
    except Exception as exc:  # noqa: BLE001 - backends raise their own types (pywintypes.error on Windows)
        raise CredentialError(f"Credential store unavailable: {exc}") from exc


def lookup(env_var: str) -> tuple[str, str] | None:
    """Return (key, source) or None. Source is SAVED or ENVIRONMENT."""
    try:
        saved = _saved(env_var)
    except CredentialError:
        saved = None  # an unreadable store must not hide a working .env key
    if saved:
        return saved, SAVED
    env = os.environ.get(env_var, "").strip()
    return (env, ENVIRONMENT) if env else None


def status(env_var: str) -> tuple[bool, bool]:
    """(a key is saved, an environment/.env key exists), for the Providers dialog."""
    try:
        saved = bool(_saved(env_var))
    except CredentialError:
        saved = False
    return saved, bool(os.environ.get(env_var, "").strip())


def save(env_var: str, key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("Enter a key first.")
    try:
        keyring.set_password(SERVICE, env_var, key)
    except Exception as exc:  # noqa: BLE001 - see _saved
        raise CredentialError(f"Could not save the key: {exc}") from exc


def delete(env_var: str) -> bool:
    """Remove the saved key. Returns False when none was saved."""
    try:
        keyring.delete_password(SERVICE, env_var)
        return True
    except PasswordDeleteError:
        return False
    except Exception as exc:  # noqa: BLE001 - see _saved
        raise CredentialError(f"Could not remove the key: {exc}") from exc
