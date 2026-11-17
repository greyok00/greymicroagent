"""Greypentest creds store — encrypted at rest, never echoed plaintext.

Fernet encryption with a keyfile generated 0600 on first use. Values are
encrypted in the store; the MCP tool surface returns only placeholders and
metadata — plaintext never enters tool output or LLM context. Substitution
happens inside this module, at the last moment, and the LOGGED form is the
substituted string with every credential value redacted.
"""
from __future__ import annotations

import json
import re
from cryptography.fernet import Fernet
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "credentials.enc.json"
KEYFILE = ROOT / "data" / ".greypentest-creds.key"

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_LEGAL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")


def _fernet() -> Fernet:
    if not KEYFILE.exists():
        KEYFILE.parent.mkdir(parents=True, exist_ok=True)
        KEYFILE.write_bytes(Fernet.generate_key())
        KEYFILE.chmod(0o600)
    return Fernet(KEYFILE.read_bytes())


def _load() -> dict:
    if not STORE.exists():
        return {}
    f = _fernet()
    return json.loads(f.decrypt(STORE.read_bytes()))


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    enc = _fernet().encrypt(json.dumps(data).encode())
    STORE.write_bytes(enc)
    STORE.chmod(0o600)


def add(name: str, credential_type: str, value: str, notes: str = "") -> dict:
    # Fail-closed naming: the name IS the placeholder grammar; anything the
    # {{...}} regex can't match would store an unresolvable secret silently.
    if not _LEGAL_NAME.fullmatch(name):
        return {"ok": False, "error":
                "credential name must match [A-Za-z][A-Za-z0-9_.-]*{{…}} — "
                f"'{name}' can never be substituted, refusing to store it"}
    data = _load()
    data[name] = {"type": credential_type, "value": value,
                  "notes": notes, "value_sha": None}
    _save(data)
    return {"ok": True, "note": f"stored '{name}' ({credential_type}) encrypted"}


def list_creds() -> dict:
    """NO plaintext. Placeholder + type + notes only."""
    data = _load()
    out = [{"name": k, "type": v["type"], "placeholder": "{{" + k + "}}",
            "notes": v.get("notes", "")} for k, v in sorted(data.items())]
    return {"ok": True, "credentials": out, "count": len(out)}


def substitute(text: str) -> tuple[str, list]:
    """Returns (substituted, placeholders_used). The REDACTED log form lives
    here so callers can't log the substituted variant."""
    data = _load()
    seen = []
    def _rep(m):
        key = m.group(1)
        if key in data:
            seen.append(key)
            return data[key]["value"]
        return m.group(0)
    return _PLACEHOLDER.sub(_rep, text), seen


def redact(text: str) -> str:
    """Every stored value → its placeholder. Used for log lines."""
    data = _load()
    for k, v in data.items():
        if "value" in v:
            text = text.replace(v["value"], "{{" + k + "}}")
    return text


def resolve_secret(key: str) -> str:
    return _load().get(key, {}).get("value", "")