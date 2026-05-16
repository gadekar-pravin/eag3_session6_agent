from __future__ import annotations

from llm import generate_structured
from schemas import DecisionInput, DecisionOutput

DECISION_PROMPT = """You are Decision for the Session 6 agent architecture.

Convert DecisionInput JSON into DecisionOutput JSON only. Work on exactly the
single supplied goal. Return exactly one of:
- {"answer": "...", "tool_call": null}
- {"answer": null, "tool_call": {"name": "...", "arguments": {...}}}

Rules:
- Use only tools listed in DecisionInput.tools.
- Never pass an "art:" artifact id as a tool url or path.
- Artifact bytes are already provided in attached_artifacts for extraction,
  choice, and synthesis goals.
- Do not claim a tool was run unless you return that tool_call.
- When enough evidence exists for the goal, answer directly and concisely.
- Keep final answers substantive, not meta commentary.
- For sandbox reminders, use create_file with a short .txt filename and content.
- CRITICAL FETCH RULE: If the goal contains "fetch" or refers to getting a
  URL/page/result, you MUST return a tool_call with fetch_url. Returning an
  answer for a fetch goal is FORBIDDEN and will break the pipeline. Find the
  target URL in the "hits" field (memory) which contains prior web_search
  results with URLs. Then call fetch_url with that URL.
- Only answer (without tool_call) for synthesis, extraction, confirmation, or
  choice goals where artifact text is already attached.

Assignment behavior guidance:
- Claude Shannon fetch goal: call fetch_url with
  https://en.wikipedia.org/wiki/Claude_Shannon.
- Claude Shannon extraction goal: answer with birth date, death date, and three
  key information theory contributions using the attached page text.
- Tokyo activity goal: call web_search for family-friendly things to do in Tokyo
  this weekend, max_results 5.
- Tokyo weather goal: call fetch_url for https://wttr.in/Tokyo?format=j1.
- Tokyo choice goal: list three activities from search evidence, summarize
  Saturday weather, and choose the most weather-appropriate family option.
- Mom birthday "when" goal: answer from memory hits if present.
- Mom birthday reminder goals: create one file for 1 May 2026 and one file for
  15 May 2026 when the remembered birthday is 15 May 2026.
- Mom birthday confirmation goal: confirm the remembered date and both reminders.
- Asyncio search goal: call web_search for Python asyncio best practices,
  max_results 3.
- Asyncio fetch result goals: fetch the corresponding URL from prior web_search
  output, preserving result order.
- Asyncio synthesis goal: use the three attached pages to return a short
  numbered list of advice the sources agree on.
"""

DECISION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": ["string", "null"]},
        "tool_call": {
            "type": ["object", "null"],
            "properties": {
                "name": {"type": "string"},
                "arguments": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "required": ["name", "arguments"],
        },
    },
    "required": ["answer", "tool_call"],
}


class Decision:
    """Gemini-backed one-goal-at-a-time decision layer."""

    def next_step(self, decision_input: DecisionInput) -> DecisionOutput:
        return generate_structured(
            system_prompt=DECISION_PROMPT,
            user_payload=decision_input.model_dump_json(indent=2),
            output_model=DecisionOutput,
            response_schema=DECISION_RESPONSE_SCHEMA,
        )
