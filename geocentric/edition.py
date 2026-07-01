"""Free/Pro edition state and feature gating.

Single codebase for everyone, free by default. `/activate <key>` redeems a
Supabase-backed license key (see geocentric/licensing.py) and unlocks Pro
locally -- no reinstall needed, and no separate build artifacts.

Deliberately NOT a DRM/anti-piracy mechanism: this is a supporter-recognition
feature, not a paid-product gate. The local entitlement file is a plain JSON
file (like the rest of the CLI's local state), not hidden or obfuscated --
proportionate to the actual threat model. Revocation has real teeth because
redemption is enforced server-side (see licensing.py's atomic single-use
RPC), and this module periodically re-verifies with the backend so a revoked
key stops granting Pro within a bounded window, while staying fully usable
offline day to day (reverify() fails open on any network error).
"""

from __future__ import annotations

import calendar
import json
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable, Optional

ENTITLEMENT_PATH = Path.home() / ".geocentric" / "entitlement.json"
REVERIFY_INTERVAL_SECONDS = 7 * 24 * 3600  # 7 days

FREE_TURN_LIMIT = 6
PRO_TURN_LIMIT = 15
FREE_MAX_EFFORT = "medium"
PRO_MAX_EFFORT = "max"
FREE_PROVIDERS = frozenset({"local", "ollama"})
EFFORT_ORDER = ["low", "medium", "high", "max"]


@dataclass
class Entitlement:
    edition: str = "free"  # "free" | "pro"
    key: Optional[str] = None
    activated_at: Optional[str] = None
    last_verified_at: Optional[str] = None

    @classmethod
    def load(cls) -> "Entitlement":
        try:
            if ENTITLEMENT_PATH.exists():
                data = json.loads(ENTITLEMENT_PATH.read_text(encoding="utf-8"))
                field_names = {f.name for f in fields(cls)}
                return cls(**{k: v for k, v in data.items() if k in field_names})
        except Exception:
            pass
        return cls()

    def save(self) -> None:
        ENTITLEMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENTITLEMENT_PATH.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")

    def is_pro(self) -> bool:
        return self.edition == "pro"


def get_entitlement() -> Entitlement:
    return Entitlement.load()


def is_pro() -> bool:
    return get_entitlement().is_pro()


def edition_label() -> str:
    return "Pro" if is_pro() else "Free"


def activate(key: str, redeem_fn: Callable[[str], tuple[bool, str]]) -> tuple[bool, str]:
    """redeem_fn is injected (rather than importing licensing.py directly)
    so this module has zero network dependency and stays trivially testable."""
    success, message = redeem_fn(key)
    if not success:
        return False, message
    Entitlement(edition="pro", key=key, activated_at=_now_iso(), last_verified_at=_now_iso()).save()
    return True, "Activated Pro."


def deactivate() -> None:
    Entitlement(edition="free").save()


def needs_reverify(ent: Optional[Entitlement] = None) -> bool:
    ent = ent or get_entitlement()
    if not ent.is_pro() or not ent.last_verified_at:
        return False
    last = _parse_iso(ent.last_verified_at)
    return last is None or (time.time() - last) > REVERIFY_INTERVAL_SECONDS


def reverify(check_fn: Callable[[str], str]) -> None:
    """check_fn returns the key's current backend status
    ('redeemed'|'revoked'|''). Fails open on any error -- offline users keep
    their cached Pro status until the backend is reachable again."""
    ent = get_entitlement()
    if not ent.is_pro() or not ent.key:
        return
    try:
        status = check_fn(ent.key)
    except Exception:
        return
    if status == "revoked":
        deactivate()
    else:
        ent.last_verified_at = _now_iso()
        ent.save()


# --- feature gates -----------------------------------------------------

def max_turn_limit() -> int:
    return PRO_TURN_LIMIT if is_pro() else FREE_TURN_LIMIT


def max_effort() -> str:
    return PRO_MAX_EFFORT if is_pro() else FREE_MAX_EFFORT


def clamp_effort(requested: str) -> str:
    cap = max_effort()
    if requested not in EFFORT_ORDER:
        return cap
    if EFFORT_ORDER.index(requested) > EFFORT_ORDER.index(cap):
        return cap
    return requested


def provider_allowed(name: str) -> bool:
    return is_pro() or name in FREE_PROVIDERS


def beta_allowed() -> bool:
    return is_pro()


def coordinator_mode_allowed() -> bool:
    return is_pro()


def plugins_allowed() -> bool:
    return is_pro()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso(value: str) -> Optional[float]:
    try:
        return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None
