from __future__ import annotations

import re

from llm import generate_structured
from schemas import DecisionInput, DecisionOutput

DECISION_PROMPT = """You are Decision for the Session 6 agent architecture.

Convert DecisionInput JSON into DecisionOutput JSON only. Work on exactly the
single supplied goal. Return exactly one of:
- {"answer": "...", "tool_call": null}
- {"answer": null, "tool_call": {"name": "...", "arguments": {...}}}

Private step-by-step procedure:
1. Identify the reasoning type for the supplied goal: lookup, fetch, file,
   arithmetic/time, extraction, comparison, choice, synthesis, or confirmation.
2. Think before you answer: inspect the goal, available tools, memory hits,
   history, and attached artifact text. Decide whether the goal needs external
   computation/tool use or can be answered from already-provided evidence.
3. Separate reasoning from tools: if external work is needed, return exactly one
   tool_call. If evidence is already sufficient, return exactly one answer.
4. Self-check before returning: exactly one output field is non-null, the tool is
   listed in DecisionInput.tools, arguments come from input evidence, no "art:"
   handle is used as a path or URL, and any answer is supported by evidence.
5. Emit only the final DecisionOutput JSON. Do not include private reasoning,
   reasoning-type labels, markdown, or explanations outside the answer string.

Rules:
- Use only tools listed in DecisionInput.tools.
- Never pass an "art:" artifact id as a tool url or path.
- Artifact bytes are already provided in attached_artifacts for extraction,
  choice, and synthesis goals.
- Do not claim a tool was run unless you return that tool_call.
- When enough evidence exists for the goal, answer directly and concisely.
- Keep final answers substantive, not meta commentary.
- Work only on the supplied goal. Do not combine later goals into the current
  tool call, file, or answer.
- Choose tool arguments from DecisionInput.query, DecisionInput.goal,
  DecisionInput.hits, DecisionInput.history, and attached_artifacts. Do not use
  memorized URLs, places, dates, topics, or answers.
- For search goals, call web_search with the user's requested topic/location and
  requested result count when present; otherwise use a concise query and the
  smallest useful result count. Do not add later constraint-gathering goals to
  the search query unless the current goal asks for them.
- CRITICAL FETCH RULE: If the goal contains "fetch" or refers to getting a
  URL/page/result, you MUST return a tool_call with fetch_url. Returning an
  answer for a fetch goal is FORBIDDEN and will break the pipeline. Use an
  explicit URL from the query/goal when present; otherwise find the requested
  ranked URL in prior web_search results from hits/history/attached_artifacts
  and call fetch_url. Preserve result order and avoid fetching a URL already
  fetched for a different ranked-result goal when another ranked URL is present.
- Only answer (without tool_call) for synthesis, extraction, confirmation, or
  choice goals where artifact text is already attached.
- For weather goals, use available weather/time tools when they fit. If only
  fetch_url is available, construct a public forecast URL from the requested
  location instead of hard-coding a city.
- For sandbox reminders, use create_file with a short lowercase .txt filename
  derived from the entity and date. If a birthday memory hit includes
  value.reminders, use those computed dates and labels. Create exactly one file
  for the current reminder goal; do not combine multiple reminder goals into one
  file unless the current goal explicitly asks for one combined file. When the
  current goal names one reminder date, the filename and content must focus on
  that date only; the next iteration will handle other reminder dates.
- For birthday recall or confirmation, answer from durable memory hits. Include
  the remembered entity and date; mention created reminders only when history
  shows successful file actions.
- For synthesis goals with multiple attached artifacts, use all attached source
  texts and return only points supported by the evidence.

Conversation loop support:
- Treat DecisionInput.history as the record of previous steps. If a prior tool
  failed and better arguments are available, retry with one corrected tool_call.
- If a prior ok action or attached artifact already satisfies the goal, answer
  directly and do not call another tool.
- Work only on the current goal because Perception will re-read history and move
  the loop to the next unfinished goal.

Fallbacks and uncertainty:
- If evidence is insufficient and a relevant listed tool can gather it, call that
  tool instead of guessing.
- If the goal requires a tool but no listed tool can perform it, answer with a
  concise limitation and the missing capability.
- If a fetch goal has no explicit URL and no URL can be found in query, goal,
  hits, history, or attached_artifacts, use web_search first when it is listed
  and suitable for discovering the URL. Only answer with a concise limitation if
  no listed tool can discover or fetch the URL; do not invent one.
- If attached artifact text is empty, irrelevant, or contradictory, say what is
  missing or uncertain rather than hallucinating a final answer.

Examples:
- Tool step:
  Goal: "Fetch the Wikipedia page for Claude Shannon"
  Output:
  {"answer": null, "tool_call": {"name": "fetch_url",
   "arguments": {"url": "https://en.wikipedia.org/wiki/Claude_Shannon"}}}
- Answer step:
  Goal: "Extract Claude Shannon's birth date, death date, and three key
  contributions to information theory"
  Attached artifact contains the page text.
  Output:
  {"answer": "Claude Shannon was born on ...", "tool_call": null}
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


def _is_fetch_goal(goal_text: str) -> bool:
    """Detect goals that require a fetch_url tool call.

    Matches imperative 'fetch' but NOT past-tense 'fetched' (which indicates
    the page is already available for extraction).
    """
    lower = goal_text.lower()
    if re.search(r"\bfetch(?:ing)?\b", lower):
        return True
    return bool(
        re.search(
            r"\b(?:read|open|retrieve|get)\b.*\b(?:url|page|webpage|website|link|result|article|content|document|site)\b",
            lower,
        )
    )


def _extract_fallback_url(decision_input: DecisionInput) -> str | None:
    """Extract a plausible URL from hits/history for a fetch goal fallback."""
    # Check history for web_search results containing URLs.
    for event in reversed(decision_input.history):
        if event.tool == "web_search" and event.result_text:
            urls = re.findall(r"https?://[^\s\"'<>]+", event.result_text)
            if urls:
                return urls[0]
    # Check hits for URLs in value fields.
    for hit in decision_input.hits:
        if hit.value:
            val_str = str(hit.value)
            urls = re.findall(r"https?://[^\s\"'<>]+", val_str)
            if urls:
                return urls[0]
    return None


class Decision:
    """Gemini-backed one-goal-at-a-time decision layer."""

    def next_step(self, decision_input: DecisionInput) -> DecisionOutput:
        output = generate_structured(
            system_prompt=DECISION_PROMPT,
            user_payload=decision_input.model_dump_json(indent=2),
            output_model=DecisionOutput,
            response_schema=DECISION_RESPONSE_SCHEMA,
            role="decision",
        )
        if output.is_answer and _is_fetch_goal(decision_input.goal.text):
            retry = generate_structured(
                system_prompt=(
                    f"{DECISION_PROMPT}\n"
                    "Correction: the supplied goal is a fetch goal. Return a "
                    "fetch_url tool_call only. Use an explicit URL from the "
                    "query/goal when present; otherwise extract the requested "
                    "ranked URL from hits, history, or attached_artifacts."
                ),
                user_payload=decision_input.model_dump_json(indent=2),
                output_model=DecisionOutput,
                response_schema=DECISION_RESPONSE_SCHEMA,
                role="decision_retry",
            )
            if not retry.is_answer:
                return retry
            # Double-failure: synthesize a fetch_url call from available data.
            url = _extract_fallback_url(decision_input)
            if url:
                from schemas import ToolCall

                return DecisionOutput(
                    answer=None,
                    tool_call=ToolCall(name="fetch_url", arguments={"url": url}),
                )
            # No URL found — cannot synthesize; return the retry as-is.
            return retry
        return output
