import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import pre_ship_check as psc


def test_import_smoke_catches_missing_dependency(tmp_path):
    bs = tmp_path / "build" / "src"
    bs.mkdir(parents=True)
    (bs / "greeter.py").write_text("import model_missing_dep_xyz\n")
    findings, evidence = psc.import_smoke(tmp_path)
    assert any("import smoke missing dep: greeter" in f and "model_missing_dep_xyz" in f
               for f in findings), findings
    assert evidence == []


def test_import_smoke_passes_closed_tree(tmp_path):
    bs = tmp_path / "build" / "src"
    bs.mkdir(parents=True)
    (bs / "goodmod.py").write_text("VALUE = 1\n")
    findings, evidence = psc.import_smoke(tmp_path)
    assert findings == [], findings
    assert evidence == ["import smoke ok: goodmod"]


def test_import_smoke_skips_build_script_with_reason(tmp_path):
    bs = tmp_path / "build" / "src"
    bs.mkdir(parents=True)
    (bs / "setup.py").write_text("raise SystemExit(3)\n")
    (bs / "goodmod.py").write_text("VALUE = 1\n")
    findings, evidence = psc.import_smoke(tmp_path)
    assert findings == [], findings
    assert evidence == ["import smoke skipped: setup (setup.py runs the cython build at import time)",
                        "import smoke ok: goodmod"]
    assert not list(tmp_path.rglob("*__pycache__*"))
