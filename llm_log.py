"""SQLite call logging for LLM interactions.

Simplified version of LLM Gateway V3's db.py — single provider, no routing
columns.  Initialise once with ``init(state_dir)`` at orchestrator start;
every ``_call_with_retry`` success/failure is logged automatically via
``llm.py``'s ``_log_ok`` / ``_log_err`` helpers.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_conn: sqlite3.Connection | None = None

_DB_NAME = "llm_calls.db"


def init(state_dir: str | Path = "state") -> None:
    """Create (or open) the call-log database inside *state_dir*."""
    global _conn  # noqa: PLW0603
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(state / _DB_NAME))
    _conn.row_factory = sqlite3.Row
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS llm_calls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL    NOT NULL,
            role        TEXT    NOT NULL,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_ms  INTEGER DEFAULT 0,
            status      TEXT    NOT NULL,
            error       TEXT
        )"""
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON llm_calls(ts DESC)")
    _conn.commit()


def log_call(
    role: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str,
    error: str | None = None,
) -> None:
    """Insert one call record.  No-op if ``init()`` has not been called."""
    if _conn is None:
        return
    _conn.execute(
        """INSERT INTO llm_calls (ts, role, input_tokens, output_tokens, latency_ms, status, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), role, input_tokens, output_tokens, latency_ms, status, error),
    )
    _conn.commit()


@dataclass
class RunSummary:
    total_calls: int
    ok_calls: int
    error_calls: int
    total_input_tokens: int
    total_output_tokens: int
    avg_latency_ms: float


def summarize() -> RunSummary | None:
    """Aggregate totals across all logged calls.  Returns ``None`` before ``init()``."""
    if _conn is None:
        return None
    row = _conn.execute(
        """SELECT COUNT(*)                                      AS total,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok,
                  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errs,
                  COALESCE(SUM(input_tokens), 0)  AS in_tok,
                  COALESCE(SUM(output_tokens), 0) AS out_tok,
                  COALESCE(AVG(latency_ms), 0)    AS avg_lat
             FROM llm_calls"""
    ).fetchone()
    if row is None or row["total"] == 0:
        return None
    return RunSummary(
        total_calls=row["total"],
        ok_calls=row["ok"],
        error_calls=row["errs"],
        total_input_tokens=row["in_tok"],
        total_output_tokens=row["out_tok"],
        avg_latency_ms=round(row["avg_lat"], 1),
    )


def close() -> None:
    """Close the database connection."""
    global _conn  # noqa: PLW0603
    if _conn is not None:
        _conn.close()
        _conn = None
