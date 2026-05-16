# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

- Install: `uv sync` then `uv run playwright install chromium` (required for fetch_url)
- Run agent: `uv run python orchestrator.py --clean "<query>"` (--clean resets state before running)
- Run all test queries: `./scripts/run_all.sh`
- Clean state: `./scripts/clean_state.sh`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Regenerate terminal output: `./scripts/run_all.sh 2>&1 | tee terminal_output.txt` (captures stdout+stderr from all 4 queries; file is gitignored)

## Architecture

Four cognitive layers with Pydantic v2 typed contracts at every boundary (schemas in `schemas.py`):

1. **Memory** (`memory.py`) — persistent JSON store (`state/memory.json`). Semantic search via token overlap, birthday extraction, artifact linking.
2. **Perception** (`perception.py`) — LLM-backed goal decomposition via Gemini 3.1 Flash Lite. Decomposes query into ordered goals, marks goals done based on history + memory facts, attaches artifact IDs to next unfinished goal.
3. **Decision** (`decision.py`) — LLM-backed one-goal-at-a-time via Gemini 3.1 Flash Lite. Returns exactly one of `answer` or `tool_call` per step.
4. **Action** (`action.py`) — dispatches MCP tool calls, stores outputs >4KB as content-addressed artifacts in `state/artifacts/`.

LLM abstraction in `llm.py`: centralizes all Gemini SDK calls with structured JSON output, auto-repair on validation failure, and temperature 0.1.

Orchestration loop in `orchestrator.py` (max 14 iterations): Memory.read → Perception.observe → Decision.next_step → Action.execute.

## Key Conventions

- All role boundary types live in `schemas.py`. Add new schemas there, not in layer modules.
- MCP stdio server (`mcp_server.py`) exposes 9 tools: web_search, fetch_url, get_time, currency_convert, read_file, list_dir, create_file, update_file, edit_file.
- Sandbox file operations are restricted to `./sandbox/` with path traversal prevention.
- Artifacts use SHA256 content hashing (first 16 chars) as filename prefix. IDs are prefixed with `art:`.

## Gotchas

- **crawl4ai stdout corruption**: crawl4ai writes Rich banners to stdout. Agent redirects FD 1→2 to prevent MCP stdio protocol corruption. Do not remove this redirect.
- **Tavily monthly cap**: Soft cap at 950/1000 calls tracked in `usage.json`. Exceeding cap falls back to DuckDuckGo (ddgs).
- **LLM Gateway**: Direct Gemini SDK used (`google-genai`) instead of LLM Gateway V3. See README for rationale.
- **Assignment-specific prompts**: Perception and Decision system prompts contain per-query guidance for the four assignment targets. This is intentional for reliability within scope.

## Environment Variables

- `GEMINI_API_KEY` — **required**. Powers Perception and Decision layers via Gemini 3.1 Flash Lite.
- `TAVILY_API_KEY` — optional. Enables premium web search; falls back to DuckDuckGo if missing or over monthly cap.

## State

- `state/memory.json` — durable memory across runs (facts, preferences, tool outcomes)
- `state/artifacts/` — content-addressed binaries (.bin) + metadata (.json)
- `usage.json` — monthly API call tracking
- `sandbox/` — sandboxed file operations for MCP tools

All state directories are gitignored. Use `--clean` flag or `./scripts/clean_state.sh` to reset.

## Assignment

For the four target queries, expected behavior, constraints, and deliverables, see @Assignment.md.
