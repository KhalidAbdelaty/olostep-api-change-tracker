"""Durable state in SQLite. Every callback and every change survives a restart."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    body_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    monitor_id TEXT,
    run_id TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS changes (
    monitor_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_created INTEGER,
    changed INTEGER,
    summary TEXT,
    decision TEXT,
    record_json TEXT,
    state TEXT NOT NULL,
    issue_number INTEGER,
    issue_url TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (monitor_id, run_id)
);

CREATE TABLE IF NOT EXISTS contracts (
    monitor_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_created INTEGER,
    endpoint TEXT,
    required_params TEXT NOT NULL,
    PRIMARY KEY (monitor_id, run_id)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def _run(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, params)

    # Deliveries: one row per callback, written before the 2xx goes back

    def add_delivery(self, body: dict) -> int:
        cur = self._run(
            "INSERT INTO deliveries (received_at, body_json) VALUES (?, ?)",
            (now_iso(), json.dumps(body, sort_keys=True)),
        )
        return cur.lastrowid

    def due_deliveries(self) -> list[sqlite3.Row]:
        return self._run(
            "SELECT * FROM deliveries WHERE status IN ('received', 'unmatched') "
            "AND next_attempt_at <= ? ORDER BY id",
            (time.time(),),
        ).fetchall()

    def update_delivery(self, delivery_id: int, status: str, note: str = "",
                        monitor_id: str | None = None, run_id: str | None = None,
                        retry_in: float = 0) -> None:
        self._run(
            "UPDATE deliveries SET status = ?, note = ?, attempts = attempts + 1, "
            "next_attempt_at = ?, monitor_id = COALESCE(?, monitor_id), "
            "run_id = COALESCE(?, run_id) WHERE id = ?",
            (status, note, time.time() + retry_in, monitor_id, run_id, delivery_id),
        )

    def get_delivery(self, delivery_id: int) -> sqlite3.Row | None:
        return self._run("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()

    # Changes: one row per verified monitor run, keyed by (monitor_id, run_id)

    def claim_change(self, monitor_id: str, run_id: str, event: dict) -> bool:
        """Insert the verified run. Returns False if this run was already recorded."""
        cur = self._run(
            "INSERT OR IGNORE INTO changes (monitor_id, run_id, event_created, changed, "
            "summary, state, updated_at) VALUES (?, ?, ?, ?, ?, 'verified', ?)",
            (monitor_id, run_id, event.get("created"), int(bool(event.get("changed"))),
             event.get("summary"), now_iso()),
        )
        return cur.rowcount == 1

    def get_change(self, monitor_id: str, run_id: str) -> sqlite3.Row | None:
        return self._run(
            "SELECT * FROM changes WHERE monitor_id = ? AND run_id = ?", (monitor_id, run_id)
        ).fetchone()

    def set_decision(self, monitor_id: str, run_id: str, decision: str,
                     record: dict, state: str) -> None:
        self._run(
            "UPDATE changes SET decision = ?, record_json = ?, state = ?, updated_at = ? "
            "WHERE monitor_id = ? AND run_id = ?",
            (decision, json.dumps(record, sort_keys=True), state, now_iso(), monitor_id, run_id),
        )

    def start_issue_attempt(self, monitor_id: str, run_id: str) -> str | None:
        """Move a change to issue_creating. Returns the previous state, or None if not allowed."""
        with self._lock:
            row = self._db.execute(
                "SELECT state FROM changes WHERE monitor_id = ? AND run_id = ?",
                (monitor_id, run_id),
            ).fetchone()
            if row is None or row["state"] not in ("issue_pending", "issue_retry", "issue_creating"):
                return None
            self._db.execute(
                "UPDATE changes SET state = 'issue_creating', attempts = attempts + 1, "
                "updated_at = ? WHERE monitor_id = ? AND run_id = ?",
                (now_iso(), monitor_id, run_id),
            )
            return row["state"]

    def finish_issue(self, monitor_id: str, run_id: str, number: int, url: str) -> None:
        self._run(
            "UPDATE changes SET state = 'issue_created', issue_number = ?, issue_url = ?, "
            "last_error = NULL, updated_at = ? WHERE monitor_id = ? AND run_id = ?",
            (number, url, now_iso(), monitor_id, run_id),
        )

    def fail_issue(self, monitor_id: str, run_id: str, error: str,
                   retry_in: float | None) -> None:
        state = "issue_retry" if retry_in is not None else "issue_failed"
        self._run(
            "UPDATE changes SET state = ?, last_error = ?, next_attempt_at = ?, updated_at = ? "
            "WHERE monitor_id = ? AND run_id = ?",
            (state, error, time.time() + (retry_in or 0), now_iso(), monitor_id, run_id),
        )

    def due_issues(self) -> list[sqlite3.Row]:
        return self._run(
            "SELECT * FROM changes WHERE state IN ('issue_pending', 'issue_retry', 'issue_creating') "
            "AND next_attempt_at <= ? ORDER BY event_created",
            (time.time(),),
        ).fetchall()

    def all_changes(self) -> list[sqlite3.Row]:
        return self._run("SELECT * FROM changes ORDER BY event_created").fetchall()

    # Contracts: the required parameters seen in each verified snapshot

    def save_contract(self, monitor_id: str, run_id: str, created: int | None,
                      endpoint: str, required: list[str]) -> None:
        self._run(
            "INSERT OR REPLACE INTO contracts VALUES (?, ?, ?, ?, ?)",
            (monitor_id, run_id, created, endpoint, json.dumps(sorted(required))),
        )

    def previous_contract(self, monitor_id: str, before_created: int | None) -> sqlite3.Row | None:
        return self._run(
            "SELECT * FROM contracts WHERE monitor_id = ? AND event_created < ? "
            "ORDER BY event_created DESC LIMIT 1",
            (monitor_id, before_created or 0),
        ).fetchone()
