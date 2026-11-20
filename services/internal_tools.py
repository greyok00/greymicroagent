#!/usr/bin/env python3
"""internal_tools.py - one-shot local tool bridge.

No MCP protocol, no standing server: the caller spawns
`python3 services/internal_tools.py call <tool>`, writes a JSON args object
on stdin, and reads one JSON result line on stdout. Every tool routes
through the agent's own registry, so the TUI and the agent loop share one
tool set.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        # Lazy tool loading: the TUI asks once for the catalog (name +
        # description + parameters) and registers only what the turn needs.
        import core.wiring as wiring
        wiring.register_all()
        import core.registry as registry
        out = []
        for schema in registry.list_tools():
            name = schema.get("name")
            if not name:
                continue
            out.append({
                "name": name,
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters") or {"type": "object", "properties": {}},
            })
        print(json.dumps(out))
        return 0
    if len(sys.argv) < 3 or sys.argv[1] != "call":
        print(json.dumps({"ok": False, "output": "",
                          "error": "usage: internal_tools.py call <tool> (args JSON on stdin) | list"}))
        return 2
    tool = sys.argv[2]
    try:
        args = json.loads(sys.stdin.read() or "{}") or {}
        if not isinstance(args, dict):
            args = {}
    except Exception as e:
        print(json.dumps({"ok": False, "output": "",
                          "error": "bad args JSON: %s" % e}))
        return 0
    import core.wiring as wiring
    wiring.register_all()
    import core.registry as registry
    result = registry.execute_tool(tool, args)
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
