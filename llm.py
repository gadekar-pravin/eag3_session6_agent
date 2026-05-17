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


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2
_BACKOFF_SECONDS = (2, 4)


def _call_with_retry(contents: str, config: types.GenerateContentConfig) -> str:
    """Call Gemini with retry on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = _client().models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )
            meta = getattr(response, "usage_metadata", None)
            if meta:
                usage.add(
                    prompt=getattr(meta, "prompt_token_count", 0) or 0,
                    completion=getattr(meta, "candidates_token_count", 0) or 0,
                    total=getattr(meta, "total_token_count", 0) or 0,
                )
            return response.text or ""
        except Exception as e:  # noqa: BLE001
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            if attempt < _MAX_RETRIES and (
                status in _RETRYABLE_STATUS_CODES
                or "timeout" in str(e).lower()
                or "unavailable" in str(e).lower()
            ):
                time.sleep(_BACKOFF_SECONDS[attempt])
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
) -> T:
    """Call Gemini and validate the JSON response against a Pydantic model."""
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_json_schema=response_schema,
        max_output_tokens=8192,
    )
    text = _call_with_retry(user_payload, config)
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
        repair_text = _call_with_retry(repair_payload, config)
        try:
            return output_model.model_validate_json(repair_text)
        except ValidationError as repair_exc:
            raise RuntimeError(
                f"Gemini structured output failed validation after repair attempt.\n"
                f"Original error: {exc}\nRepair error: {repair_exc}"
            ) from repair_exc
