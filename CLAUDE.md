# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install: `uv sync` then `uv run playwright install chromium` (required for fetch_url)
- Run agent: `uv run python agent6.py --clean "<query>"` (--clean resets state before running)
- Run all test queries: `./scripts/run_all.sh`
- Clean state: `./scripts/clean_state.sh`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

## Architecture

Four cognitive layers with Pydantic v2 typed contracts at every boundary (schemas in `schemas.py`):

1. **Memory** (`memory.py`) — persistent JSON store (`state/memory.json`). Semantic search via token overlap, birthday extraction, artifact linking.
2. **Perception** (`perception.py`) — decomposes query into ordered goals, marks goals done based on history + memory facts, attaches artifact IDs to next unfinished goal.
3. **Decision** (`decision.py`) — one-goal-at-a-time: returns exactly one of `answer` or `tool_call` per step.
4. **Action** (`action.py`) — dispatches MCP tool calls, stores outputs >4KB as content-addressed artifacts in `state/artifacts/`.

Orchestration loop in `agent6.py` (max 14 iterations): Memory.read → Perception.observe → Decision.next_step → Action.execute.

## Key Conventions

- All role boundary types live in `schemas.py`. Add new schemas there, not in layer modules.
- MCP stdio server (`mcp_server.py`) exposes 9 tools: web_search, fetch_url, get_time, currency_convert, read_file, list_dir, create_file, update_file, edit_file.
- Sandbox file operations are restricted to `./sandbox/` with path traversal prevention.
- Artifacts use SHA256 content hashing (first 16 chars) as filename prefix. IDs are prefixed with `art:`.

## Gotchas

- **Deterministic layers**: Perception and Decision are currently hardcoded for 4 specific test queries, not LLM-backed. Unrecognized queries get a generic fallback. When evolving to LLM-backed, keep the same Pydantic contracts.
- **Decision routing order**: In decision.py, goal-matching conditions must be ordered most-specific-first. Broad checks like `"search" in goal` or `"weather" in goal` will match goals that merely contain those words (e.g., "Fetch result from search results"). Always put specific checks (`"fetch result"`, `"choose"`, `"synth"`) before broad ones.
- **crawl4ai stdout corruption**: crawl4ai writes Rich banners to stdout. Agent redirects FD 1→2 to prevent MCP stdio protocol corruption. Do not remove this redirect.
- **Tavily monthly cap**: Soft cap at 950/1000 calls tracked in `usage.json`. Exceeding cap falls back to DuckDuckGo (ddgs).
- **LLM Gateway**: Intentionally not used despite assignment spec. See README for rationale.

## Environment Variables

- `TAVILY_API_KEY` — optional. Enables premium web search; falls back to DuckDuckGo if missing or over monthly cap.

## State

- `state/memory.json` — durable memory across runs (facts, preferences, tool outcomes)
- `state/artifacts/` — content-addressed binaries (.bin) + metadata (.json)
- `usage.json` — monthly API call tracking
- `sandbox/` — sandboxed file operations for MCP tools

All state directories are gitignored. Use `--clean` flag or `./scripts/clean_state.sh` to reset.

## Assignment

For the four target queries, expected behavior, constraints, and deliverables, see @Assignment.md.
