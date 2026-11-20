#!/usr/bin/env python3
"""greymicroagent model verifier.

This build runs exactly one model: the Qwen3.5 2B abliterated text model at
~/.greymicroagent/models/qwen3.5-2b-abliterated.gguf. There is no remote
download pin for it; the file must be present with the exact size and sha256.

Usage: python3 scripts/fetch_model.py verify
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

NAME = "qwen3.5-2b-abliterated.gguf"
EXPECTED_SIZE = 1244030400
EXPECTED_SHA256 = "b18f73c186906946e248bcfd921f4de36e39648d513970ff9462083b96ed1a67"


def locate() -> Path:
    """The launcher's order: explicit env, then the bundled model directory,
    then the per-user model directory."""
    env = os.environ.get("GREYMICROAGENT_MODEL_PATH")
    if env:
        return Path(env).expanduser()
    bundled = Path(__file__).resolve().parent.parent / "model" / NAME
    if bundled.is_file():
        return bundled
    return Path.home() / ".greymicroagent" / "models" / NAME


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify() -> None:
    model = locate()
    if not model.is_file():
        raise SystemExit(
            "model missing: %s\n"
            "place %s there, or in the release folder's model/ directory" % (model, NAME)
        )
    size = model.stat().st_size
    if size != EXPECTED_SIZE:
        raise SystemExit("model size %d != pinned %d - refusing" % (size, EXPECTED_SIZE))
    sha = file_sha(model)
    if sha != EXPECTED_SHA256:
        raise SystemExit("model sha256 %s != pinned %s - refusing" % (sha, EXPECTED_SHA256))
    print("OK %s (%d bytes, sha256 pinned)" % (model, size))


def main(argv) -> None:
    verb = argv[1] if len(argv) > 1 else "verify"
    if verb in ("verify", "ensure", "chain"):
        verify()
    elif verb == "download":
        raise SystemExit(
            "no remote download is pinned for this build; take %s from the release "
            "assets and place it at %s" % (NAME, locate())
        )
    else:
        raise SystemExit("unknown verb %r (verify|ensure)" % verb)


if __name__ == "__main__":
    main(sys.argv)
