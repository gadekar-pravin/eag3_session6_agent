# EAG3 Session 6 Agent Architecture Assignment

This repository implements the Session 6 role-based agent architecture:

- `memory.py` — durable JSON memory under `state/memory.json`
- `perception.py` — goal decomposition, verification and artifact attachment
- `decision.py` — one-goal-at-a-time answer-or-tool selection
- `action.py` — pure MCP dispatch and artifact storage
- `schemas.py` — Pydantic v2 contracts at every role boundary
- `agent6.py` — the orchestration loop
- `mcp_server.py` — stdio MCP server from the session notes

## Important note about the LLM Gateway

The original assignment states that every LLM call must route through LLM Gateway V3. For this submission, the gateway is intentionally **not used** because the working instruction for this build was: **"The LLM Gateway is NOT required, ignore it."**

To preserve the architectural learning objective, the implementation still uses:

- typed Pydantic contracts between roles,
- four separated cognitive layers,
- durable memory,
- artifact handling,
- MCP stdio tool dispatch,
- a loop that verifies goal completion through Perception.

The Perception and Decision layers are deterministic for the four target queries instead of LLM-backed. If you need strict compliance with the original unmodified assignment, replace `Perception.observe(...)` and `Decision.next_step(...)` with gateway-backed structured-output calls using the same schemas.

## Setup

Install dependencies with `uv`:

```bash
uv sync
```

Create `.env` if you have a Tavily key:

```bash
cp .env.example .env  # optional if you create this file locally
# then add:
# TAVILY_API_KEY=...
```

`web_search` uses Tavily when `TAVILY_API_KEY` is present and falls back to DuckDuckGo through `ddgs` otherwise. `fetch_url` uses `crawl4ai`, which may install or require a browser runtime on first use.

## Cleaning state

The assignment requires the state directory to be cleanable. Use:

```bash
./scripts/clean_state.sh
```

or run any query with `--clean`:

```bash
uv run python agent6.py --clean "When is mom's birthday?"
```

The following paths are intentionally ignored by git:

- `state/`
- `sandbox/`
- `usage.json`
- `.env`

## Target queries

### Query A — Claude Shannon artifact attach test

```bash
uv run python agent6.py --clean "Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his birth date, death date, and three key contributions to information theory."
```

Expected final answer shape:

```text
Birth date: April 30, 1916.
Death date: February 24, 2001.
Three key contributions to information theory:
1. He founded the mathematical theory of communication through his 1948 paper 'A Mathematical Theory of Communication'.
2. He formalized the bit as a unit of information and connected information content with entropy.
3. He established the noisy-channel coding theorem and the Shannon limit, showing the maximum reliable communication rate over a noisy channel.
```

Expected loop behavior: fetch page, store large fetch as an artifact, attach artifact to extraction goal, answer, verify done. Usually 3 iterations.

### Query B — Tokyo activities with weather constraint

```bash
uv run python agent6.py --clean "Find 3 family-friendly things to do in Tokyo this weekend. Check Saturday's weather forecast there and tell me which one is most appropriate."
```

Expected final answer shape:

```text
Three family-friendly Tokyo options are:
1. <activity>
2. <activity>
3. <activity>

Saturday weather: <forecast summary>. The most appropriate choice is <indoor/weather-safe activity>, because it keeps the family indoors or mostly weather-protected while still being engaging for children.
```

Expected loop behavior: search activities, fetch Tokyo weather, select the most weather-appropriate activity, verify done. Usually 4 to 6 iterations depending on network results.

### Query C — durable memory across two runs

Run 1:

```bash
uv run python agent6.py --clean "My mom's birthday is 15 May 2026. Remember that and give me a calendar reminder for two weeks before and on the day."
```

Expected final answer:

```text
Mom's birthday on 15 May 2026 is recorded, with reminders created for two weeks before and on the day.
```

Run 2, without cleaning state:

```bash
uv run python agent6.py "When is mom's birthday?"
```

Expected final answer:

```text
Mom's birthday is on 15 May 2026.
```

Expected loop behavior: run 1 stores a durable `fact` in `state/memory.json` and creates two sandbox reminder files. Run 2 answers from durable memory.

### Query D — asyncio multi-source synthesis

```bash
uv run python agent6.py --clean "Search for 'Python asyncio best practices', read the top 3 results, and give me a short numbered list of the advice they agree on."
```

Expected final answer shape:

```text
1. Use asyncio.run() as the single top-level entry point for async programs instead of manually managing the event loop.
2. Run independent coroutines concurrently with asyncio.gather() or TaskGroup rather than awaiting them one by one.
3. Do not block the event loop; move blocking I/O or CPU-heavy work into threads/processes with helpers such as asyncio.to_thread().
4. Put timeouts around external calls so one slow network operation does not hang the whole workflow.
5. Limit fan-out with semaphores or bounded queues when calling rate-limited services.
```

Expected loop behavior: search top 3 results, fetch each result, store large pages as artifacts, attach artifacts to synthesis goal, answer, verify done. Usually 6 iterations.

## Run all four checks

```bash
./scripts/run_all.sh
```

## Perception and Decision prompts plus validation JSON

The required proof-of-process files are in `prompt_validation/`:

- `prompt_validation/perception_prompt.md`
- `prompt_validation/decision_prompt.md`
- `prompt_validation/validation_examples.json`

## Actual terminal output

I could not capture live terminal output in this environment because the MCP dependencies (`mcp`, `ddgs`, `crawl4ai`, `tavily-python`) are not installed here and the environment cannot install packages. After `uv sync` on your machine, run:

```bash
./scripts/run_all.sh | tee terminal_output.txt
```

Then paste the contents of `terminal_output.txt` into this section before submitting the GitHub repository. The expected final answer shapes above are taken from the Session 6 study notes and the deterministic code paths in this implementation.
