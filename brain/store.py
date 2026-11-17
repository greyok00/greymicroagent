"""Greypentest assessment store — sqlite, lab-only scoping, plain-schema.

Assessments/cards/recon live in data/greypentest.db. ASVS grid requirements are
seeded on first use from a shipped JSON. No network, no imports of aida.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path


def _resolve_root() -> Path:
    # Adaptive root: nearest ancestor that actually ships policy.json
    # (policy.json and data/ sit at the same level in both layouts).
    here = Path(__file__).resolve().parent
    for d in (here, *here.parents):
        if (d / "policy.json").exists():
            return d
    return here.parent


ROOT = _resolve_root()
DB = ROOT / "data" / "greypentest.db"

_lock = threading.Lock()


def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    # 2026-10-31 QA (GT-07 class): WAL + busy_timeout — two writers (live run
    # + doctor) used to collide into 'database is locked' errors.
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS assessments(
                 name TEXT PRIMARY KEY, category TEXT, scope TEXT,
                 objectives TEXT, status TEXT DEFAULT 'active')""")
    c.execute("""CREATE TABLE IF NOT EXISTS cards(
                 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment TEXT,
                 card_type TEXT, title TEXT, severity TEXT, status TEXT,
                 json TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS recon(
                 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment TEXT,
                 data_type TEXT, name TEXT, json TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS asvs(
                 id TEXT PRIMARY KEY, chapter TEXT, level INT, text TEXT,
                 status TEXT DEFAULT 'NOT_TESTED', json TEXT)""")
    # 2026-10-31 QA (GT-28): pre-existing databases may predate the severity
    # column — add it if missing so INSERT doesn't fail on older DBs.
    cols = [r[1] for r in c.execute("PRAGMA table_info(cards)").fetchall()]
    if "severity" not in cols:
        c.execute("ALTER TABLE cards ADD COLUMN severity TEXT")
    return c


def create_assessment(name: str, **kw) -> dict:
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO assessments(name,category,scope,"
                  "objectives) VALUES(?,?,?,?)",
                  (name, kw.get("category", "General"),
                   kw.get("scope", ""), kw.get("objectives", "")))
        return {"ok": True, "note": f"assessment '{name}' created"}


def load_assessment(name: str) -> dict:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM assessments WHERE name=?",
                        (name,)).fetchone()
        if not row:
            return {"ok": False, "error": f"no assessment named {name!r} "
                    "(use create_assessment)"}
        return {"ok": True, "assessment": {"name": row[0], "category": row[1],
                "scope": row[2], "objectives": row[3], "status": row[4]}}


def list_assessments() -> dict:
    with _lock, _conn() as c:
        rows = c.execute("SELECT name,category FROM assessments").fetchall()
        return {"ok": True, "assessments": [dict(zip(("name", "category"), r))
                                            for r in rows]}


def add_card(assessment, card_type, title, json_blob) -> dict:
    blob = dict(json_blob or {})
    # 2026-10-31 QA (GT-28): severity promoted to a real column so cards can
    # sort/filter even when the title doesn't carry it.
    sev = (blob.get("severity") or "").upper()
    if not sev:
        m = re.match(r"(CRITICAL|HIGH|MEDIUM|LOW|INFO)\b",
                     (title or "").strip(), re.I)
        sev = m.group(1).upper() if m else ""
    # 2026-10-31 QA (GT-33): provenance — a 'finding' card must carry evidence
    # in its blob (source/proof from a scan or probe) or there must be logged
    # recon rows backing it; bare model assertions are refused.
    if (card_type or "").lower().strip("s") == "finding":
        has_ev = bool(blob.get("evidence") or blob.get("source")
                      or blob.get("proof"))
        if not has_ev:
            with _lock, _conn() as c:
                n = c.execute("SELECT COUNT(*) FROM recon WHERE assessment=?",
                              (assessment,)).fetchone()[0]
            if not n:
                return {"ok": False,
                        "error": "GT-33 provenance: 'finding' cards need a "
                        "non-empty 'evidence'/'source' field, or logged recon "
                        "rows for the assessment — run a scan / add_recon "
                        "evidence first"}
    with _lock, _conn() as c:
        c.execute("INSERT INTO cards(assessment,card_type,title,severity,"
                  "json) VALUES(?,?,?,?,?)",
                  (assessment, card_type, title, sev, json.dumps(blob)))
        i = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"ok": True, "card_id": i}


def list_cards(assessment) -> list:
    with _lock, _conn() as c:
        rows = c.execute("SELECT id,card_type,title,severity,status,json FROM "
                         "cards WHERE assessment=?", (assessment,)).fetchall()
        return [{"id": r[0], "type": r[1], "title": r[2], "severity": r[3],
                 "status": r[4], "detail": json.loads(r[5] or "{}")}
                for r in rows]


def add_recon(assessment, data_type, name, details) -> dict:
    with _lock, _conn() as c:
        c.execute("INSERT INTO recon(assessment,data_type,name,json) "
                  "VALUES(?,?,?,?)",
                  (assessment, data_type, name, json.dumps(details or {})))
        i = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"ok": True, "recon_id": i}


def list_recon(assessment, data_type=None) -> list:
    with _lock, _conn() as c:
        if data_type:
            rows = c.execute("SELECT id,data_type,name,json FROM recon WHERE "
                             "assessment=? AND data_type=? ORDER BY id DESC",
                             (assessment, data_type)).fetchall()
        else:
            rows = c.execute("SELECT id,data_type,name,json FROM recon WHERE "
                             "assessment=? ORDER BY id DESC",
                             (assessment,)).fetchall()
        return [{"id": r[0], "type": r[1], "name": r[2],
                 "details": json.loads(r[3] or "{}")} for r in rows]


def asvs_seed(reqs: list) -> int:
    with _lock, _conn() as c:
        n = 0
        for r in reqs:
            c.execute("INSERT OR REPLACE INTO asvs(id,chapter,level,text,json) "
                      "VALUES(?,?,?,?,?)",
                      (r["id"], r.get("chapter", ""), r.get("level", 1),
                       r.get("text", ""), json.dumps({})))
            n += 1
        return n


def asvs_status(req_id: str, status: str, analysis: str = "") -> dict:
    if status not in ("NOT_TESTED", "PASS", "FAIL", "NA"):
        return {"ok": False, "error": "status must be NOT_TESTED|PASS|FAIL|NA"}
    with _lock, _conn() as c:
        j = c.execute("SELECT json FROM asvs WHERE id=?", (req_id,)).fetchone()
        if not j:
            return {"ok": False, "error": f"unknown ASVS req {req_id}"}
        blob = json.loads(j[0] or "{}")
        blob["analysis"] = analysis
        c.execute("UPDATE asvs SET status=?, json=? WHERE id=?",
                  (status, json.dumps(blob), req_id))
        return {"ok": True, "note": f"{req_id} → {status}"}


def asvs_list(status=None, limit=200) -> list:
    with _lock, _conn() as c:
        if status:
            rows = c.execute("SELECT id,chapter,status,text FROM asvs WHERE "
                             "status=? LIMIT ?", (status, limit)).fetchall()
        else:
            rows = c.execute("SELECT id,chapter,status,text FROM asvs "
                             "LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "chapter": r[1], "status": r[2], "text": r[3]}
                for r in rows]


def asvs_summary() -> dict:
    with _lock, _conn() as c:
        rows = c.execute("SELECT status, count(*) FROM asvs GROUP BY "
                         "status").fetchall()
    m = {r[0]: r[1] for r in rows}
    total = sum(m.values())
    return {"ok": True, "total": total,
            "by_status": m, "remaining": m.get("NOT_TESTED", 0),
            "done": total - m.get("NOT_TESTED", 0)}