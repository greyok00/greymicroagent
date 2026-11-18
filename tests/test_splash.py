import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "build" / "src"))
import importlib, splash
importlib.reload(splash)

def test_front_door_contents():
    rows = "\n".join(splash.splash_lines())
    for s in ["GREYMICROAGENT", "/rag ingest", "/rag remove", "/rag status", "/rag temp"]:
        assert s in rows
def test_lines_nonempty_short():
    ls = splash.splash_lines()
    assert ls and len(ls) < 40
