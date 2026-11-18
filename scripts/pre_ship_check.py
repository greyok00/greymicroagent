#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

USAGE = "usage: pre_ship_check.py <payload-root>"

VENDORED_MARKERS = ("vendor/", "node_modules/")
SERVICE_PY_WHITELIST = [
    "services/child_wrap.py",
    "services/rag/__init__.py",
    "services/rag/kbcore.py",
    "services/rag_gate.py",
    "services/rag_mcp.py",
    "services/search_mcp.py",
    "services/supervision/__init__.py",
    "services/supervision/detectors.py",
    "services/supervision/fsm.py",
    "services/supervision/pump.py",
    "services/supervision/supervisor.py",
]
REQUIRED_FILES = [
    ("model/greymicroagent.txt", "model card ships as .txt"),
    ("config-data/port_policy.json", "fork port policy ships with the payload"),
    ("README.md", "product README"),
    ("THIRD-PARTY-NOTICES.txt", "third-party license notices"),
    ("state/MANIFEST.json", "frozen-tree manifest"),
    ("bin/greymicroagent", "launcher"),
        ("config-data/extensions/rag.ts", "shipped TUI extension record"),
    ("config-data/extensions/loop-guard.ts", "shipped TUI extension record"),
    ("config-data/extensions/internal_tools.ts", "shipped TUI extension record"),
    ("config-data/extensions/lib/shared.ts",
     "shared extension lib rides with the shipped record"),
]
BINARY_MAX = 512 * 1024 * 1024
CHUNK = 32 * 1024 * 1024
OVERLAP = 64
EM_DASH = b"\xe2\x80\x94"
TEXT_LAWS = [
    (b"why are you looping", "incident-class string WHY ARE YOU LOOPING"),
    (b"greymini", "codename greymini"),
    (b"/home/grey", "host path /home/grey"),
    (b"knowledge-ingestor", "pre-rebrand string knowledge-ingestor"),
]
BYTE_LAWS = TEXT_LAWS + [(EM_DASH, "em dash in shipped text")]


def is_vendored(rel):
    return rel.startswith(VENDORED_MARKERS) or "/node_modules/" in rel


def text_like(rel, data):
    return b"\x00" not in data[:8192]


def law_findings(p, rel, vendored):
    size = p.stat().st_size
    if size == 0:
        return []
    if size > BINARY_MAX:
        data = p.open("rb").read(CHUNK)
        laws = TEXT_LAWS
    else:
        data = p.read_bytes()
        if vendored:
            laws = TEXT_LAWS
        elif text_like(rel, data):
            laws = BYTE_LAWS
        else:
            laws = TEXT_LAWS
    low = data.lower()
    out = []
    for needle, label in laws:
        if needle in low:
            out.append("%s in: %s" % (label, rel))
    return out


def comment_findings(rel, path, vendored):
    if vendored:
        return []
    if not (rel.endswith(".sh") or rel == "bin/greymicroagent"):
        return []
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ["%s: unreadable for comment scan" % rel]
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("#") and not (i == 1 and s.startswith("#!")):
            out.append("%s:%d full-line comment in shipped shell surface" % (rel, i))
            if len(out) > 40:
                out.append("%s: ... more comments" % rel)
                break
    return out


def json_comment_findings(rel, path, vendored):
    if vendored or not rel.endswith(".json"):
        return []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = ln.strip()
        if s.startswith(("//", "/*", "#")):
            return ["%s: comment marker in shipped json: %s" % (rel, s[:60])]
    return []


def symlink_findings(root, rel, target):
    if target.startswith("/home/"):
        return ["%s: symlink points into a host home dir: %s" % (rel, target)]
    if target.startswith("/"):
        return []
    resolved = os.path.normpath(os.path.join(root, rel))
    base = os.path.dirname(resolved)
    abs_res = os.path.normpath(os.path.join(base, target))
    if not abs_res.startswith(str(root) + os.sep) and abs_res != str(root):
        return ["%s: symlink escapes the payload: %s" % (rel, target)]
    return []


SMOKE_SKIP = {
    "setup": "setup.py runs the cython build at import time",
    "__init__": "package marker, imported with its parent",
    "greyagent_run": "greyagent family helper, deliberately not staged",
}
SMOKE_TIMEOUT = 120
SMOKE_CHILD = ("import sys, importlib; sys.path.insert(0, sys.argv[2]); "
               "importlib.import_module(sys.argv[1]); print('OK')")


def import_candidates(build_src):
    stems = {}
    skipped = []
    hits = {}
    for f in sorted(build_src.iterdir()):
        if not f.is_file():
            continue
        if not (f.name.endswith(".py") or ".cpython" in f.name):
            continue
        stem = f.name.split(".")[0]
        hits[stem] = True
    for stem in sorted(hits):
        if stem in SMOKE_SKIP:
            skipped.append((stem, SMOKE_SKIP[stem]))
        elif stem not in stems:
            stems[stem] = None
    return sorted(stems), skipped


def import_smoke(root):
    build_src = root / "build" / "src"
    findings = []
    evidence = []
    if not build_src.is_dir():
        return [], ["import smoke skipped: no staged build/src present"]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cands, skipped = import_candidates(build_src)
    for stem, why in skipped:
        evidence.append("import smoke skipped: %s (%s)" % (stem, why))
    for name in cands:
        try:
            r = subprocess.run([sys.executable, "-B", "-c", SMOKE_CHILD, name, str(build_src)],
                               cwd=str(root), env=env, capture_output=True, text=True,
                               timeout=SMOKE_TIMEOUT)
        except subprocess.TimeoutExpired:
            findings.append("import smoke timed out after %ds (subprocess killed): %s"
                            % (SMOKE_TIMEOUT, name))
            continue
        out = (r.stdout or "").strip().splitlines()
        err_tail = (r.stderr or "").strip().splitlines()
        tail = err_tail[-1] if err_tail and err_tail[-1].strip() else (out[-1] if out else "no output")
        if r.returncode == 0 and out and out[-1].strip() == "OK":
            evidence.append("import smoke ok: %s" % name)
        elif "ModuleNotFoundError" in tail:
            findings.append("import smoke missing dep: %s: %s" % (name, tail.strip()))
        else:
            findings.append("import smoke error: %s rc=%s: %s" % (name, r.returncode, tail.strip()))
    return findings, evidence


def main(argv):
    if len(argv) != 2:
        print(USAGE)
        return 2
    root = Path(argv[1]).resolve()
    if not root.is_dir():
        print("pre_ship_check: not a directory: %s" % root)
        return 2
    findings = []
    checked = 0
    md_seen = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            rel = str(p.relative_to(root))
            findings.extend(symlink_findings(root, rel, os.readlink(p)))
            continue
        if not p.is_file():
            continue
        checked += 1
        rel = str(p.relative_to(root))
        vendored = is_vendored(rel)
        name = p.name.lower()
        if name.endswith(".md"):
            if vendored:
                pass
            elif rel == "README.md":
                md_seen.append(rel)
            else:
                findings.append("markdown in payload besides the root README: %s" % rel)
        if p.name.endswith((".bak", ".orig", ".mangled", ".regenerated", ".pyc")) \
                or p.name.endswith("-bak") or ".ga08-bak" in p.name:
            if not vendored:
                findings.append("dev residue file: %s" % rel)
        if not vendored and rel.startswith("services/") and rel.endswith(".py") \
                and rel not in SERVICE_PY_WHITELIST:
            findings.append("uncompiled services .py outside whitelist: %s" % rel)
        findings.extend(law_findings(p, rel, vendored))
        findings.extend(comment_findings(rel, p, vendored))
        findings.extend(json_comment_findings(rel, p, vendored))

    md_seen = [m for m in md_seen if m.count("/") == 0]
    if len(md_seen) != 1:
        findings.append("payload must carry exactly one root README (found %d: %s)"
                        % (len(md_seen), ",".join(md_seen) or "none"))

    for required, why in REQUIRED_FILES:
        if not (root / required).is_file():
            findings.append("missing required payload file: %s (%s)" % (required, why))

    launcher = root / "bin" / "greymicroagent"
    if launcher.is_file():
        ltxt = launcher.read_text(encoding="utf-8", errors="ignore")
        if "model/greymicroagent.txt" not in ltxt:
            findings.append("launcher does not point the card at model/greymicroagent.txt")
        if "model/greymicroagent.md" in ltxt:
            findings.append("launcher still points at the dev card name .md")
        if "GREYMICROAGENT_MODEL_PATH" not in ltxt:
            findings.append("launcher does not export GREYMICROAGENT_MODEL_PATH (home-resolved model path)")
    policy = root / "config-data" / "port_policy.json"
    if policy.is_file():
        ptxt = policy.read_text(encoding="utf-8", errors="ignore")
        if "7640-7647" not in ptxt:
            findings.append("port policy does not declare the 7640-7647 fork block")


    smoke_findings, smoke_evidence = import_smoke(root)
    for line in smoke_evidence:
        print("  " + line)
    findings.extend(smoke_findings)

    if findings:
        print("pre_ship_check: FAIL (%d findings over %d files)" % (len(findings), checked))
        for f in findings:
            print("  " + f)
        return 1
    print("pre_ship_check: PASS (%d files scanned)" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
