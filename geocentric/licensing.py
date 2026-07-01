"""Supabase-backed Pro license key redemption and admin management.

Two trust tiers:
- Public (redeem/check): uses the publishable key, safe to ship in every
  install -- Postgres RLS plus the two narrow RPC functions are the actual
  security boundary (see the pro_keys schema), not secrecy of this key.
- Admin (issue/revoke/list): uses the secret key, which bypasses RLS
  entirely and can therefore read/write the table directly. This key is
  NEVER hardcoded or shipped -- it's read from the local OS keychain, which
  only exists on the machine where the project owner explicitly stored it
  (same `keyring` mechanism as geocentric/agent/keys.py's ApiKeyStore, under
  a separate 'geocentric-code-admin' service name so a normal user's
  keychain never has it).
"""

from __future__ import annotations

import platform
import secrets
import string
from typing import Any, Optional

import httpx

# Public project identity -- safe to ship. Protected by RLS + narrow RPC
# grants (see the SQL schema), not by secrecy.
SUPABASE_URL = "https://wisxvfegntpbiuayneby.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_rdYh2bsyNWoIF1fP5iQoDA_DMDY8rbX"

_ADMIN_SERVICE_NAME = "geocentric-code-admin"


def _admin_secret_key() -> Optional[str]:
    try:
        import keyring

        return keyring.get_password(_ADMIN_SERVICE_NAME, "supabase_secret_key")
    except Exception:
        return None


def has_admin_access() -> bool:
    return bool(_admin_secret_key())


def _rest_url(path: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{path.lstrip('/')}"


def _public_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {SUPABASE_PUBLISHABLE_KEY}",
        "Content-Type": "application/json",
    }


def _admin_headers() -> dict[str, str]:
    secret = _admin_secret_key()
    if not secret:
        raise RuntimeError(
            "No admin Supabase key in the local keychain -- admin commands only work "
            "on the machine where the project owner ran the initial setup."
        )
    return {"apikey": secret, "Authorization": f"Bearer {secret}", "Content-Type": "application/json"}


# --- public: used by every install's /activate --------------------------

def redeem_key(key: str) -> tuple[bool, str]:
    key = key.strip()
    if not key:
        return False, "empty_key"
    try:
        resp = httpx.post(
            _rest_url("rpc/redeem_pro_key"),
            headers=_public_headers(),
            json={"input_key": key, "fingerprint": platform.node() or ""},
            timeout=10.0,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return False, "no_response"
        row = rows[0]
        return bool(row.get("success")), str(row.get("message") or "")
    except httpx.HTTPError as exc:
        return False, f"network_error: {exc}"


def check_key_status(key: str) -> str:
    resp = httpx.post(
        _rest_url("rpc/check_pro_key_status"),
        headers=_public_headers(),
        json={"input_key": key},
        timeout=10.0,
    )
    resp.raise_for_status()
    rows = resp.json()
    return str(rows[0].get("status") or "") if rows else ""


# --- admin: only works with the secret key present locally --------------

def _generate_key(length: int = 24) -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(length))
    return "-".join(raw[i : i + 4] for i in range(0, length, 4))


def admin_issue_key(note: str = "") -> str:
    key = _generate_key()
    resp = httpx.post(
        _rest_url("pro_keys"),
        headers={**_admin_headers(), "Prefer": "return=representation"},
        json={"key": key, "note": note},
        timeout=10.0,
    )
    resp.raise_for_status()
    return key


def admin_revoke_key(key: str) -> bool:
    resp = httpx.patch(
        _rest_url(f"pro_keys?key=eq.{key}"),
        headers={**_admin_headers(), "Prefer": "return=representation"},
        json={"status": "revoked"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return len(resp.json()) > 0


def admin_list_keys() -> list[dict[str, Any]]:
    resp = httpx.get(
        _rest_url("pro_keys?select=key,status,note,created_at,redeemed_at&order=created_at.desc"),
        headers=_admin_headers(),
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()
