import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "greylocalrag"


def test_floor_default_is_calibration_choice():
    text = LAUNCHER.read_text(encoding="utf-8")
    m = re.search(r'GREYLOCALRAG_RAG_FLOOR="?\$\{GREYLOCALRAG_RAG_FLOOR:-([0-9.]+)\}"?', text)
    assert m, "launcher must carry the explicit RAG floor tunable form"
    assert float(m.group(1)) == 7.5


def test_floor_retune_artifact_agrees_when_present():
    art = ROOT / "state" / "bench" / "floor-calibration-2.json"
    if not art.exists():
        return
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["chosen_floor"] == 7.5
    band = data["max_margin_band"]
    assert band and min(band) <= 7.5 <= max(band) + 0.01
    assert data["summary"]["after"]["share_max"] < 7.5
    assert data["summary"]["after"]["clean_max"] == 0.0
    assert data["summary"]["after"]["share_max"] < data["summary"]["before"]["share_max"]


def test_floor_calibration_artifact_agrees_when_present():
    art = ROOT / "state" / "bench" / "floor-calibration.json"
    if not art.exists():
        return
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["chosen_floor"] == 19.0
    band = data["max_margin_band"]
    assert band and min(band) <= 19.0 <= max(band) + 0.01
    assert data["summary"]["clean_max"] == 0.0


def test_dbs_default_covers_commands_and_general():
    text = LAUNCHER.read_text(encoding="utf-8")
    m = re.search(r'GREYLOCALRAG_DBS="?([^"\n]+)"?', text)
    assert m, "launcher must export GREYLOCALRAG_DBS"
    names = [x.strip() for x in m.group(1).split(",") if x.strip()]
    assert names[0] == "commands" and names[1] == "general"
