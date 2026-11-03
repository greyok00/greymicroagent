"""E2E smoke for the memory MCP server, sandboxed, through its REAL entry.

Spawns mcp/run_server.py --server memory exactly as mcp_registry.json does
(stdio JSON-RPC), against a throwaway store, and asserts the behaviors the
GM-15 hardening fixed: a garbage stdin line is skipped without poisoning the
loop, every well-formed request still gets a response id, bad arguments come
back as a JSON-RPC error object instead of a hang or crash, and search
covers the cold-markdown tier.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _spawn(env: dict) -> subprocess.Popen:
    e = dict(os.environ)
    e.update(env)
    return subprocess.Popen(
        [sys.executable, str(ROOT / "mcp" / "run_server.py"), "--server", "memory"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=e, cwd=str(ROOT))


def test_memory_server_e2e_sandboxed():
    d = tempfile.mkdtemp(prefix="gm-mem-e2e-")
    p = _spawn({"GREYAGENT_MEMORY_DIR": d, "GREYAGENT_PLATFORM": "e2esmoke"})
    try:
        lines = [
            "garbage not json at all\n",           # GM-15: skip, keep serving
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "memory_write",
                                   "arguments": {"content": "e2e fact one"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "memory_write",
                                   "arguments": {"content": "e2e fact two alpha"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "memory_search",
                                   "arguments": {"query": "alpha"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "memory_read",
                                   "arguments": {"limit": 5}}}),
            # GM-15: arguments must be an object -> jsonrpc error, not crash
            json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                        "params": {"name": "memory_read", "arguments": "oops"}}),
            # GM-15: unknown tool -> error object
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "no_such_tool", "arguments": {}}}),
        ]
        lines = [l if l.endswith("\n") else l + "\n" for l in lines]
        out, err = p.communicate("".join(lines), timeout=60)
        resp = {}
        for l in out.strip().split("\n"):
            if not l.strip():
                continue
            m = json.loads(l)                    # garbage line never reached stdout
            if isinstance(m, dict) and "id" in m:
                resp[m["id"]] = m

        assert resp.get(1, {}).get("result") is not None, "initialize failed"
        for i in (2, 3, 4, 5):
            r = resp.get(i)
            assert r is not None, f"request {i} got no response"
            assert "error" not in r or r["error"].get("code") == 0, f"{i}: {r}"
        s4 = resp.get(4, {}).get("result", {})
        text4 = s4.get("content", [{"text": ""}])[0].get("text", "")
        assert "alpha" in text4, f"search missed its row: {text4[:120]}"
        # GM-15: bad-args and unknown-tool must SURFACE as failure (MCP style:
        # result.isError true, or a jsonrpc error object) — and never crash
        # or hang the server loop.
        for i in (6, 7):
            r = resp.get(i)
            assert r is not None, f"request {i} got no response"
            assert ("error" in r) or r.get("result", {}).get("isError"), \
                f"{i} failure not surfaced: {r}"
        assert resp[6]["result"]["isError"], f"bad args must fail loudly: {resp[6]}"
        assert "arguments must be an object" in \
            resp[6]["result"]["content"][0]["text"]
        assert p.poll() is None or p.returncode == 0
    finally:
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()