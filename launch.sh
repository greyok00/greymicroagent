#!/usr/bin/env bash
# greymicroagent — Linux launcher.
# Opens the product in the desktop's terminal when a session is available,
# otherwise runs it in this shell. The Windows twin is launch.ps1.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LAUNCH="$HERE/bin/greymicroagent"
if [ ! -x "$LAUNCH" ]; then
  echo "greymicroagent: $LAUNCH missing or not executable" >&2
  exit 1
fi

if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  if command -v x-terminal-emulator >/dev/null 2>&1; then
    exec x-terminal-emulator -e "$LAUNCH" "$@"
  elif command -v gnome-terminal >/dev/null 2>&1; then
    exec gnome-terminal -- "$LAUNCH" "$@"
  elif command -v konsole >/dev/null 2>&1; then
    exec konsole -e "$LAUNCH" "$@"
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    exec xfce4-terminal -e "$LAUNCH" "$@"
  elif command -v xterm >/dev/null 2>&1; then
    exec xterm -e "$LAUNCH" "$@"
  fi
fi

exec "$LAUNCH" "$@"
