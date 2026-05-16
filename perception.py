from __future__ import annotations

from llm import generate_structured
from schemas import PerceptionInput, PerceptionOutput

PERCEPTION_PROMPT = """You are Perception for the Session 6 agent architecture.

Convert PerceptionInput JSON into PerceptionOutput JSON only. Your job is to
decompose the original query into bounded goals, preserve goal identity across
iterations, mark goals done from evidence, and attach artifact ids when raw
artifact text is needed by the next unfinished goal.

Rules:
- Return JSON matching exactly: {"observation": {"goals": [...]}}.
- If prior_goals is empty, create a small ordered goal list for the query.
- If prior_goals is present, keep the same goal ids, text, and order unless the
  existing list is plainly invalid.
- A goal is done only when history has an ok action or answer for that goal_id,
  or when durable memory hits already satisfy that goal.
- A "fetch" goal is done ONLY when history has an ok fetch_url action for that
  goal_id. A web_search result or an answer does NOT satisfy a fetch goal.
- For durable birthday queries, the "record birthday" goal is done when a memory
  hit contains entity "mom" and attribute "birthday".
- Attach artifact ids only to goals that directly need to READ those bytes for
  extraction, choice, or synthesis.
- NEVER attach artifacts to a "fetch" goal. Fetch goals need zero attachments —
  the URL comes from history/memory hits, not from reading artifact bytes.
- Only attach fetched-page artifacts to the final synthesis/extraction goal.
- Use artifact ids from memory hits and history events. Never invent artifact ids.
- Keep all later unfinished goals without attachments.

Assignment target decomposition guidance:
- Claude Shannon query: fetch the Wikipedia page, then extract birth date,
  death date, and three information theory contributions.
- Tokyo query: find three family-friendly activities, check Saturday weather,
  then choose the best weather-appropriate activity.
- Mom birthday run 1: record durable memory, create two-weeks-before reminder,
  create day-of reminder, confirm.
- Mom birthday run 2: answer from durable memory.
- Asyncio query: search, fetch result 1, fetch result 2, fetch result 3,
  then synthesize agreed advice.
"""

PERCEPTION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "observation": {
            "type": "object",
            "properties": {
                "goals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "done": {"type": "boolean"},
                            "attach_artifact_id": {"type": ["string", "null"]},
                            "attach_artifact_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["id", "text", "done", "attach_artifact_ids"],
                    },
                }
            },
            "required": ["goals"],
        }
    },
    "required": ["observation"],
}


class Perception:
    """Gemini-backed goal decomposition and verification layer."""

    def observe(self, perception_input: PerceptionInput) -> PerceptionOutput:
        return generate_structured(
            system_prompt=PERCEPTION_PROMPT,
            user_payload=perception_input.model_dump_json(indent=2),
            output_model=PerceptionOutput,
            response_schema=PERCEPTION_RESPONSE_SCHEMA,
        )
