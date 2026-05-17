from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

MODEL_NAME = "gemini-3.1-flash-lite"

T = TypeVar("T", bound=BaseModel)


@dataclass
class UsageAccumulator:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

    def add(self, prompt: int, completion: int, total: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.call_count += 1

    def reset(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.call_count = 0


usage = UsageAccumulator()


load_dotenv(Path(__file__).parent / ".env")


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(_missing_key_message())
    return genai.Client(api_key=api_key)


def _missing_key_message() -> str:
    return (
        "GEMINI_API_KEY is required for Gemini-backed Perception and Decision. "
        "Add it to .env or export it before running orchestrator.py."
    )


def require_gemini_configured() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError(_missing_key_message())


# Gemini prompt caching requires >= 32,768 tokens of cached content.
# Our system prompts are ~2000-4000 tokens, well below threshold.
# Infrastructure is ready for when prompts grow (e.g., adding many few-shot examples).
_CACHE_MIN_TOKENS = 32_768

_MAX_RETRIES = 3


# ── SQLite call logging (optional; wired when llm_log.init() is called) ──


def _log_ok(role: str, input_tokens: int, output_tokens: int, latency_ms: int) -> None:
    try:
        from llm_log import log_call

        log_call(role, input_tokens, output_tokens, latency_ms, "ok")
    except Exception:  # noqa: BLE001
        pass  # logging must never break the hot path


def _log_err(role: str, latency_ms: int, err: Exception) -> None:
    try:
        from llm_log import log_call

        log_call(role, 0, 0, latency_ms, "error", str(err)[:200])
    except Exception:  # noqa: BLE001
        pass


# ── Schema cleaning helpers (ported from LLM Gateway V3 providers.py) ──


def _gemini_inline_refs(schema: dict) -> dict:
    """Resolve ``$ref`` references to ``$defs`` / ``definitions`` inline.

    Pydantic emits refs for nested models.  Gemini's responseSchema endpoint
    rejects ``$ref``, so we inline before cleaning.  Must run BEFORE
    ``_gemini_clean_schema`` (which strips ``$defs``).
    """
    if not isinstance(schema, dict):
        return schema
    defs = dict(schema.get("$defs") or schema.get("definitions") or {})

    def walk(node, seen: frozenset[str] = frozenset()) -> dict | list:
        if isinstance(node, dict):
            if "$ref" in node:
                target = node["$ref"]
                name = None
                if target.startswith("#/$defs/"):
                    name = target.removeprefix("#/$defs/")
                elif target.startswith("#/definitions/"):
                    name = target.removeprefix("#/definitions/")
                if name and name in defs and name not in seen:
                    resolved = walk(defs[name], seen | {name})
                    extras = {k: walk(v, seen) for k, v in node.items() if k != "$ref"}
                    if isinstance(resolved, dict):
                        return {**resolved, **extras}
                    return resolved
                # Unresolvable ref — drop it; Gemini would 400 anyway.
                return {k: walk(v, seen) for k, v in node.items() if k != "$ref"}
            return {k: walk(v, seen) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(x, seen) for x in node]
        return node

    return walk(schema)  # type: ignore[return-value]


def _gemini_clean_schema(schema: dict) -> dict:
    """Strip JSON-Schema keys Gemini rejects, after inlining ``$ref`` / ``$defs``.

    ``additionalProperties`` is only stripped when ``False`` (Pydantic default
    that Gemini rejects).  When ``True`` it is preserved — it tells Gemini the
    object accepts arbitrary keys (critical for free-form tool arguments).
    """
    schema = _gemini_inline_refs(schema)
    if not isinstance(schema, dict):
        return schema
    drop_always = {"$schema", "title", "definitions", "$defs", "examples", "default"}

    def strip(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in drop_always:
                    continue
                if k == "additionalProperties" and v is False:
                    continue
                out[k] = strip(v)
            return out
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node

    return strip(schema)


def _backoff_for(err: Exception) -> tuple[float, str]:
    """Return (wait_seconds, reason) based on error type.

    wait=0 with non-empty reason → abort (non-retryable).
    wait=0 with empty reason → unknown error, raise immediately.
    """
    msg = str(err).lower()
    status = getattr(err, "status_code", None) or getattr(err, "code", None)
    if status == 429:
        if "queue" in msg:
            return 15.0, "server queue full"
        if "quota" in msg or "rpm" in msg or "per minute" in msg:
            return 60.0, "RPM quota"
        if "rpd" in msg or "per day" in msg or "daily" in msg:
            return 0.0, "RPD exhausted"
        return 30.0, "rate limited"
    if status and 500 <= status < 600:
        return 20.0, f"upstream {status}"
    if status == 408 or "timeout" in msg:
        return 10.0, "timeout"
    if status in (401, 403):
        return 0.0, "auth error"
    if "unavailable" in msg:
        return 15.0, "unavailable"
    return 0.0, ""


def _call_with_retry(
    contents: str,
    config: types.GenerateContentConfig,
    *,
    role: str = "unknown",
) -> str:
    """Call Gemini with retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            response = _client().models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            meta = getattr(response, "usage_metadata", None)
            p_tok = (getattr(meta, "prompt_token_count", 0) or 0) if meta else 0
            c_tok = (getattr(meta, "candidates_token_count", 0) or 0) if meta else 0
            if meta:
                usage.add(
                    prompt=p_tok,
                    completion=c_tok,
                    total=getattr(meta, "total_token_count", 0) or 0,
                )
            _log_ok(role, p_tok, c_tok, latency_ms)
            return response.text or ""
        except Exception as e:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - t0) * 1000)
            wait, reason = _backoff_for(e)
            _log_err(role, latency_ms, e)
            if wait > 0 and attempt < _MAX_RETRIES:
                time.sleep(wait)
                last_exc = e
                continue
            if reason:
                # Non-retryable error with a known reason — raise immediately.
                raise
            if attempt < _MAX_RETRIES:
                # Unknown error — still retry with a short pause.
                time.sleep(2)
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]


def generate_structured(
    *,
    system_prompt: str,
    user_payload: str,
    output_model: type[T],
    response_schema: dict,
    role: str = "unknown",
) -> T:
    """Call Gemini and validate the JSON response against a Pydantic model."""
    cleaned = _gemini_clean_schema(response_schema)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_json_schema=cleaned,
        max_output_tokens=8192,
    )
    text = _call_with_retry(user_payload, config, role=role)
    try:
        return output_model.model_validate_json(text)
    except ValidationError as exc:
        repair_payload = (
            "The previous response did not validate against the required schema.\n"
            f"Validation error:\n{exc}\n\n"
            "Return only corrected JSON for the same task. Do not add prose.\n\n"
            f"Original task payload:\n{user_payload}\n\n"
            f"Invalid response:\n{text}"
        )
        repair_text = _call_with_retry(repair_payload, config, role=f"{role}_repair")
        try:
            return output_model.model_validate_json(repair_text)
        except ValidationError as repair_exc:
            raise RuntimeError(
                f"Gemini structured output failed validation after repair attempt.\n"
                f"Original error: {exc}\nRepair error: {repair_exc}"
            ) from repair_exc
