"""Portable scheduler store (Windows source fallback).

A small SQLite task table under the product state directory. The compiled
module exposes the same two calls the tool layer uses: create and list.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path


def _db() -> Path:
    base = (os.environ.get("GREYMICROAGENT_STATE_DIR")
            or os.environ.get("CORTEXAGENT_STATE_DIR")
            or str(Path.home() / ".greymicroagent" / "state"))
    folder = Path(base).expanduser() / "scheduler"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "tasks.db"


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else _db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "title TEXT NOT NULL, kind TEXT, payload TEXT,"
                "created TEXT, done INTEGER DEFAULT 0)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=10)

    def create(self, title: str = "", kind: str = "user", payload=None, **kw):
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (title, kind, payload, created) VALUES (?,?,?,?)",
                (str(title or "task"), str(kind or "user"),
                 json.dumps(payload or {}, ensure_ascii=False),
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            return cur.lastrowid

    def list(self, limit: int = 50) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, kind, payload, created, done FROM tasks "
                "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r[0], "title": r[1], "kind": r[2],
                 "payload": r[3], "created": r[4], "done": bool(r[5])}
                for r in rows]

    def get(self, task_id: int):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, title, kind, payload, created, done FROM tasks WHERE id=?",
                (int(task_id),)).fetchone()
        return row

    def complete(self, task_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("UPDATE tasks SET done=1 WHERE id=?", (int(task_id),))
            return cur.rowcount > 0
