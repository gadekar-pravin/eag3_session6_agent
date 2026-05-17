"""Tests for llm_log.py: init, log_call, summarize, close."""

import sqlite3

import llm_log


def test_init_creates_db(tmp_path):
    llm_log.init(tmp_path)
    db_path = tmp_path / "llm_calls.db"
    assert db_path.exists()
    llm_log.close()


def test_log_call_inserts_row(tmp_path):
    llm_log.init(tmp_path)
    llm_log.log_call("perception", 100, 50, 200, "ok")
    conn = sqlite3.connect(str(tmp_path / "llm_calls.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM llm_calls").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["role"] == "perception"
    assert rows[0]["input_tokens"] == 100
    assert rows[0]["output_tokens"] == 50
    assert rows[0]["latency_ms"] == 200
    assert rows[0]["status"] == "ok"
    assert rows[0]["error"] is None
    llm_log.close()


def test_log_call_with_error(tmp_path):
    llm_log.init(tmp_path)
    llm_log.log_call("decision", 0, 0, 100, "error", "timeout exceeded")
    conn = sqlite3.connect(str(tmp_path / "llm_calls.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM llm_calls").fetchone()
    conn.close()
    assert row["status"] == "error"
    assert row["error"] == "timeout exceeded"
    llm_log.close()


def test_log_call_noop_before_init():
    llm_log._conn = None
    llm_log.log_call("test", 0, 0, 0, "ok")  # should not raise


def test_summarize_empty(tmp_path):
    llm_log.init(tmp_path)
    result = llm_log.summarize()
    assert result is None
    llm_log.close()


def test_summarize_aggregates(tmp_path):
    llm_log.init(tmp_path)
    llm_log.log_call("perception", 100, 50, 200, "ok")
    llm_log.log_call("decision", 200, 80, 300, "ok")
    llm_log.log_call("decision", 0, 0, 50, "error", "timeout")

    summary = llm_log.summarize()
    assert summary is not None
    assert summary.total_calls == 3
    assert summary.ok_calls == 2
    assert summary.error_calls == 1
    assert summary.total_input_tokens == 300
    assert summary.total_output_tokens == 130
    assert summary.avg_latency_ms > 0
    llm_log.close()


def test_summarize_before_init():
    llm_log._conn = None
    assert llm_log.summarize() is None


def test_close_idempotent(tmp_path):
    llm_log.init(tmp_path)
    llm_log.close()
    llm_log.close()  # should not raise
    assert llm_log._conn is None
