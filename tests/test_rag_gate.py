import sys, json, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import rag_gate

BODY = {"model": "greylocalrag", "temperature": 0.9,
        "messages": [{"role": "user", "content": "how do I mirror directories"}]}

def test_temp_clamped():
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "http://127.0.0.1:1")
    req = json.loads(out)
    assert 0.0 <= req["temperature"] <= 0.2

def test_no_grounding_marker_on_empty_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(tmp_path))
    monkeypatch.delenv("GREYLOCALRAG_DBS", raising=False)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "http://127.0.0.1:1")
    msgs = json.loads(out)["messages"]
    assert json.dumps(msgs[-1]).find("NO-KB-GROUNDING") >= 0

def test_grounding_block_injected(tmp_path, monkeypatch):
    import rag.kbcore as kb
    dbs = tmp_path / "dbs"; dbs.mkdir()
    monkeypatch.setenv("GREYLOCALRAG_DBS_ROOT", str(dbs))
    monkeypatch.setenv("GREYLOCALRAG_DBS", "commands")
    monkeypatch.setenv("GREYLOCALRAG_RAG_FLOOR", "0.0")
    db = kb.db_dir("commands"); kb.init_db(db, note="t")
    kb.add_records(db, kb.records_from("robocopy /MIR mirrors a directory tree exactly and completely.", {"t": "robocopy", "src": "t", "url": "u", "date": "d"}), enc=None)
    code, out = rag_gate.handle(json.dumps(BODY).encode(), "http://127.0.0.1:1")
    last = json.loads(out)["messages"][-1]["content"]
    assert "[KB:commands#1 score=" in last and "robocopy" in last

def test_no_request_logging(tmp_path):
    assert not list(tmp_path.rglob("*.log"))
