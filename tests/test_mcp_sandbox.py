from unittest.mock import patch

import pytest

from mcp_server import SANDBOX, _safe, edit_file, get_time


class TestSafePath:
    def test_normal_path(self):
        result = _safe("notes.txt")
        assert result == (SANDBOX / "notes.txt").resolve()

    def test_traversal_rejected(self):
        with pytest.raises(ValueError, match="escapes the sandbox"):
            _safe("../etc/passwd")

    def test_absolute_rejected(self):
        with pytest.raises(ValueError, match="escapes the sandbox"):
            _safe("/etc/passwd")

    def test_nested_traversal_rejected(self):
        with pytest.raises(ValueError, match="escapes the sandbox"):
            _safe("subdir/../../etc/passwd")


class TestGetTime:
    def test_utc(self):
        result = get_time("UTC")
        assert result["timezone"] == "UTC"
        assert result["offset_hours"] == 0.0
        assert "T" in result["iso"]

    def test_offset_kolkata(self):
        result = get_time("Asia/Kolkata")
        assert result["offset_hours"] == 5.5
        assert result["timezone"] == "Asia/Kolkata"


class TestEditFile:
    def test_single_occurrence(self, tmp_sandbox):
        f = tmp_sandbox / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        with patch("mcp_server.SANDBOX", tmp_sandbox):
            result = edit_file("test.txt", "hello", "goodbye")
        assert result["replacements"] == 1
        assert f.read_text() == "goodbye world"

    def test_multiple_without_flag_raises(self, tmp_sandbox):
        f = tmp_sandbox / "test.txt"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        with patch("mcp_server.SANDBOX", tmp_sandbox):
            with pytest.raises(ValueError, match="occurs 2 times"):
                edit_file("test.txt", "aaa", "ccc")

    def test_replace_all(self, tmp_sandbox):
        f = tmp_sandbox / "test.txt"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        with patch("mcp_server.SANDBOX", tmp_sandbox):
            result = edit_file("test.txt", "aaa", "ccc", replace_all=True)
        assert result["replacements"] == 2
        assert f.read_text() == "ccc bbb ccc"

    def test_not_found_raises(self, tmp_sandbox):
        f = tmp_sandbox / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        with patch("mcp_server.SANDBOX", tmp_sandbox):
            with pytest.raises(ValueError, match="not found"):
                edit_file("test.txt", "xyz", "abc")
