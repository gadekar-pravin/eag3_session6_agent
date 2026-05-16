# Decision Prompt

Decision is backed by Gemini Flash-Lite structured output.

Responsibilities:
1. Convert `DecisionInput` JSON into `DecisionOutput` JSON only.
2. Work on exactly one bounded goal.
3. Return exactly one of: a final answer, or one MCP tool call.
4. Use only MCP tools listed in `DecisionInput.tools`.
5. Never pass `art:` handles to MCP tools; artifact bytes are supplied separately by the loop.
6. When the goal is extraction, comparison, selection, or synthesis, produce a substantive answer rather than a meta response.

Validation contract: `DecisionInput -> DecisionOutput`, where exactly one of `answer` or `tool_call` is populated.
