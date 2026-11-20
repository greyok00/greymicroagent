"""greymicroagent console entry for the frozen Windows build.

Boots the vendored model server binary next to the frozen tree, waits for
its health endpoint, then runs a plain console chat. Grounding and prompt
minification live in the full product boot (bin/greymicroagent on Linux);
this frozen console path keeps Windows parity to the model itself.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)
if IS_FROZEN:
    ROOT = Path(sys.argv[0]).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "core").is_dir() and (p / "vendor").is_dir():
            return p
    return start


def main() -> int:
    root = find_root(ROOT)
    model_path = Path(os.environ.get("GREYMICROAGENT_MODEL_PATH")
                      or (Path.home() / ".greymicroagent"
                          / "models" / "qwen3.5-2b-abliterated.gguf"))
    if not model_path.exists():
        print("greymicroagent: model missing at %s" % model_path)
        print("set GREYMICROAGENT_MODEL_PATH or place the gguf there.")
        return 1

    server_bin = (root / "vendor" / "win" / "greymicroagent-server.exe")
    if not server_bin.exists():
        server_bin = (root / "vendor" / "greymicroagent-server"
                      / "greymicroagent-server")
    port = int(os.environ.get("GREYMICROAGENT_MODEL_PORT") or 7640)
    proc = subprocess.Popen([
        str(server_bin),
        "-m", str(model_path),
        "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", os.environ.get("GREYAGENT_CTX") or "65536",
    ])
    atexit_ok = True
    try:
        import atexit
        atexit.register(proc.terminate)
    except Exception:
        atexit_ok = False

    base = "http://127.0.0.1:%d" % port
    for _ in range(300):
        try:
            import requests
            r = requests.get(base + "/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1.0)
    else:
        print("greymicroagent: model server did not come up on %s" % base)
        return 1
    print("greymicroagent: model up on %s - type a message (empty line quits)" % base)

    import requests
    history = []
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        history.append({"role": "user", "content": line})
        try:
            r = requests.post(base + "/v1/chat/completions", json={
                "model": "greymicroagent",
                "messages": history if len(history) < 40 else history[-20:],
                "stream": False,
            }, timeout=600)
            data = r.json()
            reply = data["choices"][0]["message"]["content"]
        except Exception as e:
            print("error: %s" % e)
            continue
        history.append({"role": "assistant", "content": reply})
        print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
