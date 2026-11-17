import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "greylocalrag"


def test_floor_default_is_calibration_choice():
    text = LAUNCHER.read_text(encoding="utf-8")
    m = re.search(r'GREYLOCALRAG_RAG_FLOOR="?\$\{GREYLOCALRAG_RAG_FLOOR:-([0-9.]+)\}"?', text)
    assert m, "launcher must carry the explicit RAG floor tunable form"
    assert float(m.group(1)) == 19.0


def test_floor_calibration_artifact_agrees_when_present():
    art = ROOT / "state" / "bench" / "floor-calibration.json"
    if not art.exists():
        return
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["chosen_floor"] == 19.0
    band = data["max_margin_band"]
    assert band and min(band) <= 19.0 <= max(band) + 0.01
    assert data["summary"]["clean_max"] == 0.0
