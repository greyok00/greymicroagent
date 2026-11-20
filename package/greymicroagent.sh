#!/usr/bin/env bash
set -e
PKG_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$PKG_DIR")"
cd "$ROOT"

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

missing=""
command -v python3 >/dev/null 2>&1 || missing="$missing python3"
node_ok() {
  command -v node >/dev/null 2>&1 || return 1
 _major=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
  [ "${_major:-0}" -ge 22 ] 2>/dev/null
}
node_ok || missing="$missing nodejs"

if [ -n "$missing" ]; then
  echo "greymicroagent: installing missing system dependencies:$missing"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update
    $SUDO apt-get install -y $missing build-essential
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y $missing gcc gcc-c++
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -S --needed --noconfirm python nodejs
  else
    echo "greymicroagent: install python3 and nodejs (>=22) manually, then rerun" >&2
    exit 1
  fi
fi

echo "greymicroagent: installing python dependencies"
python3 -m pip install --user -q -r "$PKG_DIR/requirements.txt" 2>/dev/null \
  || python3 -m pip install -q -r "$PKG_DIR/requirements.txt" \
  || python3 -m pip install --break-system-packages -q -r "$PKG_DIR/requirements.txt"

echo "greymicroagent: frozen-tree gate"
python3 "$ROOT/bin/verify_compiled.py" || {
  echo "greymicroagent: frozen tree out of sync; run scripts/gen_manifest.py after any build" >&2
  exit 1
}

echo "greymicroagent: launching"
exec "$ROOT/bin/greymicroagent" "$@"
