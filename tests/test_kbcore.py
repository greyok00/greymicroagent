import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "services"))
import rag.kbcore as kb

def test_chunk_never_empty():
    assert len(kb.chunk("one heading\n\nbody text that is long enough to clear the engine's own forty-character floor with room to spare", 2400)) >= 1

def test_records_carry_provenance():
    recs = kb.records_from("Heading\n\nBody about commands, written long enough to clear the floor threshold the engine applies to every chunk.", {"t": "cmd", "src": "seed", "url": "https://x", "date": "2026-11-17"})
    r = recs[0]
    assert r["src"] == "seed" and r["url"] == "https://x" and r["date"] == "2026-11-17"

def test_keyword_search_works_model_off(tmp_path):
    db = kb.db_dir("t-probe")
    kb.init_db(db, note="probe")
    kb.add_records(db, kb.records_from("Robocopy mirrors directories exactly.\n\nUsage: robocopy source destination /MIR mirrors a full tree.", {"t": "robocopy", "src": "seed", "url": "u", "date": "d"}), enc=None)
    hits = kb.search(db, "mirror directories with robocopy", 5, enc=None)
    assert hits and "robocopy" in str(hits[0]).lower()
    import shutil; shutil.rmtree(db, ignore_errors=True)
