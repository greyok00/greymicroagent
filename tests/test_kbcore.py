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

FLOOR = 7.5

def test_stopword_guard_is_query_side_only():
    assert len(kb.STOPWORDS) >= 60 and len(kb.STOPWORDS) == len(set(kb.STOPWORDS))
    assert all(w == w.lower() and w.isalpha() for w in kb.STOPWORDS)
    assert "robocopy" not in kb.STOPWORDS and "dns" not in kb.STOPWORDS and "top" not in kb.STOPWORDS
    assert "the" in kb.STOPWORDS and "about" in kb.STOPWORDS and "which" in kb.STOPWORDS

def test_stopword_only_query_hits_nothing(tmp_path):
    db = kb.db_dir("t-stop")
    kb.init_db(db, note="probe")
    kb.add_records(db, kb.records_from("The command was introduced long before this record existed.\n\nIt is one of those entries that reads like prose and carries plenty of shared words across the lines.", {"t": "prose entry", "src": "seed", "url": "u", "date": "d"}), enc=None)
    for q in ("what was it about", "the of and", "why does that not work"):
        assert kb.search(db, q, 5, enc=None) == []
    rows = kb.pack_rows(db)
    assert any(" that " in r["x"].lower() and " the " in r["x"].lower() for r in rows)
    import shutil; shutil.rmtree(db, ignore_errors=True)

def test_real_command_query_keeps_its_hit():
    db = kb.db_dir("t-real")
    kb.init_db(db, note="probe")
    kb.add_records(db, kb.records_from("Robocopy mirrors directories with the /MIR switch and it copies a whole directory tree.", {"t": "robocopy", "src": "seed", "url": "u", "date": "d"}), enc=None)
    hits = kb.search(db, "how do I mirror a directory tree with robocopy", 5, enc=None)
    assert hits and hits[0]["lex"] >= FLOOR and "robocopy" in hits[0]["t"].lower()
    import shutil; shutil.rmtree(db, ignore_errors=True)

def test_shareword_off_topic_query_scores_below_floor():
    db = kb.db_dir("t-share")
    kb.init_db(db, note="probe")
    seeds = [
        ("robocopy", "Robocopy mirrors the whole tree and it does that with the /MIR switch for a clean copy."),
        ("netsh", "Netsh shows the network configuration that the system keeps for every interface it has."),
        ("shutdown", "Shutdown closes the system down on a timer and it was designed for that exact job alone."),
    ]
    kb.add_records(db, [r for t, x in seeds for r in kb.records_from(x, {"t": t, "src": "seed", "url": "u", "date": "d"})], enc=None)
    for q in ("what is the capital of Portugal and its full history",
              "what do you think about the meaning of life and the universe"):
        hits = kb.search(db, q, 6, enc=None)
        top = max((float(h.get("lex") or 0.0) for h in hits), default=0.0)
        assert top < FLOOR, f"{q!r} leaked lexical score {top} over floor {FLOOR}"
    import shutil; shutil.rmtree(db, ignore_errors=True)

def test_same_url_reingest_dedups_and_url_text_is_searchable(tmp_path):
    db = kb.db_dir("t-urldedup")
    kb.init_db(db, note="probe")
    first = kb.add_records(db, kb.records_from(
        "Robocopy mirrors directories exactly.\n\nUsage: robocopy source destination /MIR mirrors a full tree.",
        {"t": "mirror page", "src": "web", "url": "https://example.com/mirror", "date": "d"}), enc=None)
    assert first
    # The page's text changed, so the content key differs and only the url
    # can catch the re-ingest; before the url key was normalized this
    # appended a full duplicate set for one source.
    second = kb.add_records(db, kb.records_from(
        "The mirror page changed its wording entirely, so the stored content no longer matches it.\n\nRobocopy still ships with every Windows install today.",
        {"t": "mirror page", "src": "web", "url": "https://example.com/mirror", "date": "d"}), enc=None)
    assert second == [], f"re-ingest of the same url appended {len(second)} duplicate records"
    assert len(kb.pack_rows(db)) == len(first)
    hits = kb.search(db, "https://example.com/mirror", 5, enc=None)
    assert hits and hits[0]["i"] == first[0]
    import shutil; shutil.rmtree(db, ignore_errors=True)
