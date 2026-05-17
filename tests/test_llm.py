"""Tests for llm.py pure functions: _backoff_for, _gemini_inline_refs, _gemini_clean_schema."""

from llm import (
    _backoff_for,
    _gemini_clean_schema,
    _gemini_inline_refs,
)

# ── _backoff_for ─────────────────────────────────────────────────────────


class _FakeError(Exception):
    def __init__(self, msg: str = "", status_code: int | None = None):
        super().__init__(msg)
        self.status_code = status_code


def test_backoff_429_queue():
    wait, reason = _backoff_for(_FakeError("queue is full", status_code=429))
    assert wait == 15.0
    assert "queue" in reason


def test_backoff_429_rpm():
    wait, reason = _backoff_for(_FakeError("RPM quota exceeded", status_code=429))
    assert wait == 60.0
    assert "RPM" in reason


def test_backoff_429_per_minute():
    wait, reason = _backoff_for(_FakeError("rate limit per minute", status_code=429))
    assert wait == 60.0


def test_backoff_429_rpd():
    wait, reason = _backoff_for(_FakeError("RPD limit reached", status_code=429))
    assert wait == 0.0
    assert reason  # non-empty = abort


def test_backoff_429_daily():
    wait, reason = _backoff_for(_FakeError("daily limit", status_code=429))
    assert wait == 0.0
    assert reason


def test_backoff_429_generic():
    wait, reason = _backoff_for(_FakeError("slow down", status_code=429))
    assert wait == 30.0


def test_backoff_500():
    wait, reason = _backoff_for(_FakeError("internal", status_code=500))
    assert wait == 20.0
    assert "500" in reason


def test_backoff_503():
    wait, reason = _backoff_for(_FakeError("", status_code=503))
    assert wait == 20.0


def test_backoff_timeout_by_status():
    wait, _ = _backoff_for(_FakeError("", status_code=408))
    assert wait == 10.0


def test_backoff_timeout_by_message():
    wait, _ = _backoff_for(_FakeError("connection timeout"))
    assert wait == 10.0


def test_backoff_auth_401():
    wait, reason = _backoff_for(_FakeError("unauthorized", status_code=401))
    assert wait == 0.0
    assert reason  # non-empty = abort


def test_backoff_auth_403():
    wait, reason = _backoff_for(_FakeError("forbidden", status_code=403))
    assert wait == 0.0
    assert reason


def test_backoff_unavailable():
    wait, _ = _backoff_for(_FakeError("service unavailable"))
    assert wait == 15.0


def test_backoff_unknown():
    wait, reason = _backoff_for(_FakeError("something weird"))
    assert wait == 0.0
    assert reason == ""


def test_backoff_uses_code_attr():
    """Fallback to .code when .status_code is absent."""

    class _Err(Exception):
        code = 429

    wait, _ = _backoff_for(_Err("rate limited"))
    assert wait == 30.0


# ── _gemini_inline_refs ──────────────────────────────────────────────────


def test_inline_refs_no_refs():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert _gemini_inline_refs(schema) == schema


def test_inline_refs_simple():
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {"Child": {"type": "object", "properties": {"name": {"type": "string"}}}},
    }
    result = _gemini_inline_refs(schema)
    assert "$ref" not in str(result)
    assert result["properties"]["child"]["type"] == "object"


def test_inline_refs_definitions_key():
    schema = {
        "type": "object",
        "properties": {"item": {"$ref": "#/definitions/Item"}},
        "definitions": {"Item": {"type": "string"}},
    }
    result = _gemini_inline_refs(schema)
    assert result["properties"]["item"]["type"] == "string"


def test_inline_refs_cycle_detection():
    schema = {
        "type": "object",
        "properties": {"self": {"$ref": "#/$defs/Node"}},
        "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}},
    }
    result = _gemini_inline_refs(schema)
    # Should not recurse infinitely; the second $ref is dropped.
    assert "$ref" not in str(result)


def test_inline_refs_non_dict():
    assert _gemini_inline_refs("not a dict") == "not a dict"


# ── _gemini_clean_schema ─────────────────────────────────────────────────


def test_clean_schema_strips_keys():
    schema = {
        "type": "object",
        "title": "MyModel",
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": False,
        "examples": [{"x": 1}],
        "default": {},
        "properties": {
            "x": {"type": "string", "title": "X", "default": "hello"},
        },
    }
    result = _gemini_clean_schema(schema)
    assert "title" not in result
    assert "$schema" not in result
    assert "additionalProperties" not in result
    assert "examples" not in result
    assert "default" not in result
    assert result["type"] == "object"
    assert "title" not in result["properties"]["x"]
    assert "default" not in result["properties"]["x"]


def test_clean_schema_strips_defs_after_inlining():
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/Child"}},
        "$defs": {"Child": {"type": "object", "properties": {"name": {"type": "string"}}}},
    }
    result = _gemini_clean_schema(schema)
    assert "$defs" not in result
    assert "$ref" not in str(result)
    assert result["properties"]["child"]["type"] == "object"


def test_clean_schema_preserves_additional_properties_true():
    schema = {
        "type": "object",
        "properties": {
            "args": {"type": "object", "additionalProperties": True},
        },
    }
    result = _gemini_clean_schema(schema)
    assert result["properties"]["args"]["additionalProperties"] is True


def test_clean_schema_strips_additional_properties_false():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }
    result = _gemini_clean_schema(schema)
    assert "additionalProperties" not in result


def test_clean_schema_preserves_required():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    result = _gemini_clean_schema(schema)
    assert result["required"] == ["x"]


def test_clean_schema_non_dict():
    assert _gemini_clean_schema("not a dict") == "not a dict"
