"""Metadata store: SQLite index for project revisions, benchmarks, and training runs."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


SCHEMA = """\
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    metrics TEXT NOT NULL,
    recorded_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    config TEXT NOT NULL,
    best_epoch INTEGER,
    best_val_loss REAL,
    test_mAP REAL,
    recorded_at TEXT DEFAULT (datetime('now'))
);
"""


class MetadataStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def log_benchmark(self, run_id: str, kind: str, metrics: dict) -> None:
        self._conn.execute(
            "INSERT INTO benchmarks (run_id, kind, metrics) VALUES (?, ?, ?)",
            (run_id, kind, json.dumps(metrics)),
        )
        self._conn.commit()

    def log_training_run(self, model_name: str, config: dict, best_epoch: int,
                         best_val_loss: float, test_mAP: float) -> None:
        self._conn.execute(
            "INSERT INTO training_runs (model_name, config, best_epoch, best_val_loss, test_mAP) VALUES (?,?,?,?,?)",
            (model_name, json.dumps(config), best_epoch, best_val_loss, test_mAP),
        )
        self._conn.commit()

    def list_benchmarks(self, kind: str | None = None) -> list[dict]:
        q = "SELECT * FROM benchmarks"
        args: tuple = ()
        if kind:
            q += " WHERE kind = ?"
            args = (kind,)
        rows = self._conn.execute(q + " ORDER BY recorded_at DESC", args).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
