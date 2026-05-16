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
- Decompose by capability, not by memorized examples: remember durable facts,
  search for unknown URLs/lists, fetch explicit URLs or selected search results,
  create requested files/reminders, then synthesize or answer.
- If prior_goals is present, keep the same goal ids, text, and order unless the
  existing list is plainly invalid.
- A goal is done only when history has an ok action or answer for that goal_id,
  or when durable memory hits already satisfy that goal.
- Do not mark a later goal done just because an earlier action incidentally
  mentions it. Separate search, fetch, file, and reminder goals require their
  own matching evidence.
- A "fetch" goal is done ONLY when history has an ok fetch_url action for that
  goal_id. A web_search result or an answer does NOT satisfy a fetch goal.
- A "remember" or "record" goal is done when durable memory hits contain the
  requested fact, preference, or outcome. For birthday facts, match any entity
  from the query, not only one particular person.
- File/reminder creation goals are done only when history has an ok create_file,
  update_file, or edit_file action for that goal_id.
- Attach artifact ids only to goals that directly need to READ those bytes for
  extraction, choice, or synthesis.
- A fetch goal may attach a prior web_search artifact when it needs to read
  ranked result URLs. Do not attach fetched-page artifacts to fetch goals.
- Attach fetched-page artifacts to extraction, choice, and synthesis goals.
- Use artifact ids from memory hits and history events. Never invent artifact ids.
- Keep all later unfinished goals without attachments.
- For requests to read the top N search results, create one search goal, one
  fetch goal per requested result in rank order, then one synthesis goal.
  NEVER collapse multiple fetch goals into one. Each URL requires its own goal.
- For requests combining options with a constraint such as weather, create goals
  to gather options, gather the constraint evidence, then choose from evidence.
- Keep goals specific enough that Decision can choose exactly one tool call or
  answer for the next unfinished goal.
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
