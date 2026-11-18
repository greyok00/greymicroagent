import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "greylocalrag"
TEMPLATE = ROOT / "config-data" / "mcp-registry-template.json"

sys.path.insert(0, str(ROOT / "scripts"))
import pre_ship_check as psc

SERVER_NAMES = {"memory", "knowledge", "greysearch", "browser"}


def _seeding_block():
    lines = LAUNCHER.read_text(encoding="utf-8").splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("_seed_mcp_registry() {")]
    assert len(starts) == 1, "launcher must define the seeding function exactly once"
    start = starts[0]
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    assert any(ln == "_seed_mcp_registry" for ln in lines[end + 1:]), \
        "launcher must actually invoke the seeding function"
    return "\n".join(lines[start:end + 1])


def _run_seeding(homedir, invocations=2):
    script = (
        "set -euo pipefail\n"
        "ROOT=%s\n"
        "HOME=%s\n"
        "%s\n"
        "%s\n" % (json.dumps(str(ROOT)), json.dumps(str(homedir)),
                  _seeding_block(), "_seed_mcp_registry\n" * invocations)
    )
    env = dict(os.environ)
    env["HOME"] = str(homedir)
    env.pop("GREYAGENT_CODING_AGENT_DIR", None)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env=env)


def test_template_carries_the_three_portable_servers():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "/home/" not in text, "template must carry zero host paths"
    data = json.loads(text)
    servers = {s["name"]: s for s in data["servers"]}
    assert set(servers) == SERVER_NAMES
    assert servers["memory"]["args"][1:3] == ["--server", "memory"]
    for name, s in servers.items():
        assert s["command"] == "python3", name
        assert s["args"], name
        assert s.get("enabled") is True, name
        for arg in s["args"]:
            if arg.startswith("/"):
                assert arg.startswith("/opt/greylocalrag/"), (name, arg)


def test_pre_ship_gate_accepts_the_portable_template(tmp_path):
    payload = tmp_path / "payload"
    (payload / "config-data").mkdir(parents=True)
    (payload / "config-data" / "mcp-registry-template.json").write_text(
        TEMPLATE.read_text(encoding="utf-8"))
    assert psc.registry_template_findings(payload) == []


def test_pre_ship_gate_rejects_missing_host_and_incomplete_templates(tmp_path):
    payload = tmp_path / "payload"
    (payload / "config-data").mkdir(parents=True)
    findings = psc.registry_template_findings(payload)
    assert any("missing MCP registry template" in f for f in findings), findings

    host = json.loads(TEMPLATE.read_text())
    for s in host["servers"]:
        s["args"] = [a.replace("/opt/greylocalrag", "/home/grey/greylocalrag")
                     for a in s["args"]]
    (payload / "config-data" / "mcp-registry-template.json").write_text(json.dumps(host))
    findings = psc.registry_template_findings(payload)
    assert any("host path" in f for f in findings), findings

    incomplete = json.loads(TEMPLATE.read_text())
    incomplete["servers"] = [s for s in incomplete["servers"] if s["name"] != "greysearch"]
    (payload / "config-data" / "mcp-registry-template.json").write_text(json.dumps(incomplete))
    findings = psc.registry_template_findings(payload)
    assert any("missing server entries: greysearch" in f for f in findings), findings


def test_first_launch_seeds_registry_and_second_launch_never_overwrites(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r = _run_seeding(home, invocations=2)
    assert r.returncode == 0, r.stderr
    reg = home / ".greylocalrag" / "agent" / "mcp_registry.json"
    assert reg.is_file(), "first launch must land the registry"
    assert reg.read_bytes() == TEMPLATE.read_bytes(), \
        "the seeded copy is the template verbatim"
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert {s["name"] for s in data["servers"]} == SERVER_NAMES
    assert r.stdout.count("seeded") == 1, \
        "exactly one seeding message across two calls: %r" % r.stdout
    first_bytes = reg.read_bytes()
    first_mtime = reg.stat().st_mtime_ns
    r2 = _run_seeding(home, invocations=1)
    assert r2.returncode == 0, r2.stderr
    assert "seeded" not in r2.stdout, "a seeded home must not reseed on the next boot"
    assert reg.read_bytes() == first_bytes, "second boot rewrote the registry"
    assert reg.stat().st_mtime_ns == first_mtime, "second boot touched the registry"
