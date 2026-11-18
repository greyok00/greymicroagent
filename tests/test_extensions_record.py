import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECORD = ROOT / "config-data"
EXT_DIR = RECORD / "extensions"
LAUNCHER = ROOT / "bin" / "greymicroagent"
LIVE_TS = [
    "greysearch_core.ts",
    "gwp-onboarding.ts",
    "gwp-progress.ts",
    "loop-guard.ts",
    "mcp_client.ts",
    "mcp-panels.ts",
    "mcp-toggle.ts",
    "models.ts",
    "modes.ts",
    "permissions.ts",
    "rag.ts",
    "sampling-guard.ts",
    "thinking.ts",
]
CORE_TS = ("rag.ts", "loop-guard.ts", "mcp_client.ts")
RECORD_LAWS = (
    "/home/grey",
    "why are you looping",
    "greymini",
    "knowledge-ingestor",
)
POLICY_LAWS = (
    "/home/grey",
    "why are you looping",
    "knowledge-ingestor",
)


def test_record_exists_with_full_live_set():
    assert EXT_DIR.is_dir(), "config-data/extensions record dir must exist"
    names = sorted(p.name for p in EXT_DIR.glob("*.ts"))
    assert names == sorted(LIVE_TS), names


def test_core_extension_files_present():
    for name in CORE_TS:
        assert (EXT_DIR / name).is_file(), "missing extension record: %s" % name
    assert (EXT_DIR / "lib" / "shared.ts").is_file(), "missing shared extension lib"


def test_record_has_no_bak_residue():
    leftovers = [
        p.name
        for p in EXT_DIR.rglob("*")
        if p.is_file()
        and (p.name.endswith(("-bak", ".bak", ".ts.bak")) or ".ga08-bak" in p.name)
    ]
    assert leftovers == [], leftovers


def test_extension_sources_carry_no_host_paths_or_incident_strings():
    for p in sorted(EXT_DIR.rglob("*.ts")):
        low = p.read_bytes().lower()
        for needle in RECORD_LAWS:
            assert needle.encode() not in low, "%s in %s" % (needle, p.relative_to(ROOT))


def test_port_policy_record_laws():
    low = (RECORD / "port_policy.json").read_bytes().lower()
    for needle in POLICY_LAWS:
        assert needle.encode() not in low, "%s in port policy record" % needle


def test_port_policy_record_declares_fork_block():
    text = (RECORD / "port_policy.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert "7640-7647" in text, "port policy record must declare the fork block"
    assert "other_families_off_limits" in data


def test_launcher_copies_record_before_dev_symlink():
    text = LAUNCHER.read_text(encoding="utf-8")
    block = text[text.index('_ext_src="$HOME/.greymicroagent/agent/extensions"'):text.index("_seed_mcp_registry")]
    record_line = block.index('_ext_record="$ROOT/config-data/extensions"')
    dev_line = block.index('_ext_dev="$ROOT/config/extensions"')
    assert record_line < dev_line, "launcher must prefer the config-data record"
    assert '[ -d "$_ext_record" ]' in block
    assert '[ "$(realpath "$_ext_src" 2>/dev/null)" != "$(realpath "$_ext_record")" ]' in block
    assert 'elif [ -d "$_ext_dev" ] && [ "$(realpath "$_ext_src" 2>/dev/null)" != "$(realpath "$_ext_dev")" ]' in block
