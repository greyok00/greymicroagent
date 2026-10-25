from __future__ import annotations
import json
import re
from cryptography.fernet import Fernet
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / 'data' / 'credentials.enc.json'
KEYFILE = ROOT / 'data' / '.greyteam-creds.key'
_PLACEHOLDER = re.compile('\\{\\{\\s*([A-Za-z0-9_.-]+)\\s*\\}\\}')
_LEGAL_NAME = re.compile('[A-Za-z][A-Za-z0-9_.-]{0,63}')

def _fernet() -> Fernet:
    if not KEYFILE.exists():
        KEYFILE.parent.mkdir(parents=True, exist_ok=True)
        KEYFILE.write_bytes(Fernet.generate_key())
        KEYFILE.chmod(384)
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
    STORE.chmod(384)

def add(name: str, credential_type: str, value: str, notes: str='') -> dict:
    if not _LEGAL_NAME.fullmatch(name):
        return {'ok': False, 'error': f"credential name must match [A-Za-z][A-Za-z0-9_.-]*{{{{…}}}} — '{name}' can never be substituted, refusing to store it"}
    data = _load()
    data[name] = {'type': credential_type, 'value': value, 'notes': notes, 'value_sha': None}
    _save(data)
    return {'ok': True, 'note': f"stored '{name}' ({credential_type}) encrypted"}

def list_creds() -> dict:
    data = _load()
    out = [{'name': k, 'type': v['type'], 'placeholder': '{{' + k + '}}', 'notes': v.get('notes', '')} for k, v in sorted(data.items())]
    return {'ok': True, 'credentials': out, 'count': len(out)}

def substitute(text: str) -> tuple[str, list]:
    data = _load()
    seen = []

    def _rep(m):
        key = m.group(1)
        if key in data:
            seen.append(key)
            return data[key]['value']
        return m.group(0)
    return (_PLACEHOLDER.sub(_rep, text), seen)

def redact(text: str) -> str:
    data = _load()
    for k, v in data.items():
        if 'value' in v:
            text = text.replace(v['value'], '{{' + k + '}}')
    return text

def resolve_secret(key: str) -> str:
    return _load().get(key, {}).get('value', '')