from __future__ import annotations
import json
import sqlite3
import threading
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'greyteam.db'
_lock = threading.Lock()

def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS assessments(\n                 name TEXT PRIMARY KEY, category TEXT, scope TEXT,\n                 objectives TEXT, status TEXT DEFAULT 'active')")
    c.execute('CREATE TABLE IF NOT EXISTS cards(\n                 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment TEXT,\n                 card_type TEXT, title TEXT, severity TEXT, status TEXT,\n                 json TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS recon(\n                 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment TEXT,\n                 data_type TEXT, name TEXT, json TEXT)')
    c.execute("CREATE TABLE IF NOT EXISTS asvs(\n                 id TEXT PRIMARY KEY, chapter TEXT, level INT, text TEXT,\n                 status TEXT DEFAULT 'NOT_TESTED', json TEXT)")
    return c

def create_assessment(name: str, **kw) -> dict:
    with _lock, _conn() as c:
        c.execute('INSERT OR REPLACE INTO assessments(name,category,scope,objectives) VALUES(?,?,?,?)', (name, kw.get('category', 'General'), kw.get('scope', ''), kw.get('objectives', '')))
        return {'ok': True, 'note': f"assessment '{name}' created"}

def load_assessment(name: str) -> dict:
    with _lock, _conn() as c:
        row = c.execute('SELECT * FROM assessments WHERE name=?', (name,)).fetchone()
        if not row:
            return {'ok': False, 'error': f'no assessment named {name!r} (use create_assessment)'}
        return {'ok': True, 'assessment': {'name': row[0], 'category': row[1], 'scope': row[2], 'objectives': row[3], 'status': row[4]}}

def list_assessments() -> dict:
    with _lock, _conn() as c:
        rows = c.execute('SELECT name,category FROM assessments').fetchall()
        return {'ok': True, 'assessments': [dict(zip(('name', 'category'), r)) for r in rows]}

def add_card(assessment, card_type, title, json_blob) -> dict:
    with _lock, _conn() as c:
        c.execute('INSERT INTO cards(assessment,card_type,title,json) VALUES(?,?,?,?)', (assessment, card_type, title, json.dumps(json_blob)))
        i = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        return {'ok': True, 'card_id': i}

def list_cards(assessment) -> list:
    with _lock, _conn() as c:
        rows = c.execute('SELECT id,card_type,title,json FROM cards WHERE assessment=?', (assessment,)).fetchall()
        return [{'id': r[0], 'type': r[1], 'title': r[2], 'detail': json.loads(r[3] or '{}')} for r in rows]

def add_recon(assessment, data_type, name, details) -> dict:
    with _lock, _conn() as c:
        c.execute('INSERT INTO recon(assessment,data_type,name,json) VALUES(?,?,?,?)', (assessment, data_type, name, json.dumps(details or {})))
        i = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        return {'ok': True, 'recon_id': i}

def list_recon(assessment, data_type=None) -> list:
    with _lock, _conn() as c:
        if data_type:
            rows = c.execute('SELECT id,data_type,name,json FROM recon WHERE assessment=? AND data_type=? ORDER BY id DESC', (assessment, data_type)).fetchall()
        else:
            rows = c.execute('SELECT id,data_type,name,json FROM recon WHERE assessment=? ORDER BY id DESC', (assessment,)).fetchall()
        return [{'id': r[0], 'type': r[1], 'name': r[2], 'details': json.loads(r[3] or '{}')} for r in rows]

def asvs_seed(reqs: list) -> int:
    with _lock, _conn() as c:
        n = 0
        for r in reqs:
            c.execute('INSERT OR REPLACE INTO asvs(id,chapter,level,text,json) VALUES(?,?,?,?,?)', (r['id'], r.get('chapter', ''), r.get('level', 1), r.get('text', ''), json.dumps({})))
            n += 1
        return n

def asvs_status(req_id: str, status: str, analysis: str='') -> dict:
    if status not in ('NOT_TESTED', 'PASS', 'FAIL', 'NA'):
        return {'ok': False, 'error': 'status must be NOT_TESTED|PASS|FAIL|NA'}
    with _lock, _conn() as c:
        j = c.execute('SELECT json FROM asvs WHERE id=?', (req_id,)).fetchone()
        if not j:
            return {'ok': False, 'error': f'unknown ASVS req {req_id}'}
        blob = json.loads(j[0] or '{}')
        blob['analysis'] = analysis
        c.execute('UPDATE asvs SET status=?, json=? WHERE id=?', (status, json.dumps(blob), req_id))
        return {'ok': True, 'note': f'{req_id} → {status}'}

def asvs_list(status=None, limit=200) -> list:
    with _lock, _conn() as c:
        if status:
            rows = c.execute('SELECT id,chapter,status,text FROM asvs WHERE status=? LIMIT ?', (status, limit)).fetchall()
        else:
            rows = c.execute('SELECT id,chapter,status,text FROM asvs LIMIT ?', (limit,)).fetchall()
        return [{'id': r[0], 'chapter': r[1], 'status': r[2], 'text': r[3]} for r in rows]

def asvs_summary() -> dict:
    with _lock, _conn() as c:
        rows = c.execute('SELECT status, count(*) FROM asvs GROUP BY status').fetchall()
    m = {r[0]: r[1] for r in rows}
    total = sum(m.values())
    return {'ok': True, 'total': total, 'by_status': m, 'remaining': m.get('NOT_TESTED', 0), 'done': total - m.get('NOT_TESTED', 0)}