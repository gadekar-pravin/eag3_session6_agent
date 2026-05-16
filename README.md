# EAG3 Session 6 Agent Architecture Assignment

This repository implements the Session 6 role-based agent architecture:

- `memory.py` — durable JSON memory under `state/memory.json`
- `perception.py` — Gemini-backed goal decomposition, verification and artifact attachment
- `decision.py` — Gemini-backed one-goal-at-a-time answer-or-tool selection
- `action.py` — pure MCP dispatch and artifact storage
- `llm.py` — direct Gemini Flash-Lite structured-output helper
- `schemas.py` — Pydantic v2 contracts at every role boundary
- `agent6.py` — the orchestration loop
- `mcp_server.py` — stdio MCP server from the session notes

## Important note about LLM calls

This build intentionally does **not** use LLM Gateway V3. The working instruction for this version is: **"The LLM Gateway is NOT required, ignore it."**

Perception and Decision are real LLM-backed layers using direct Gemini API calls to `gemini-3.1-flash-lite` with JSON structured output validated by the existing Pydantic contracts. The implementation still preserves:

- typed Pydantic contracts between roles,
- four separated cognitive layers,
- durable memory,
- artifact handling,
- MCP stdio tool dispatch,
- a loop that verifies goal completion through Perception.

## Setup

Install dependencies with `uv`:

```bash
uv sync
uv run playwright install chromium
```

Create `.env` with a Gemini API key. Tavily is optional:

```bash
cp .env.example .env  # optional if you create this file locally
# then add:
# GEMINI_API_KEY=...
# TAVILY_API_KEY=...
```

`GEMINI_API_KEY` is required for the Perception and Decision LLM calls. `web_search` uses Tavily when `TAVILY_API_KEY` is present and falls back to DuckDuckGo through `ddgs` otherwise. `fetch_url` uses `crawl4ai` and requires the Playwright Chromium runtime.

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

```
--- Query A: Claude Shannon ---

--- iter 1 ---
[memory.read] 0 hit(s)
[perception] [open] Fetch the Wikipedia page for Claude Shannon.
[perception] [open] Extract birth date, death date, and three key contributions to information theory from the fetched page.
[decision] TOOL_CALL: fetch_url({'url': 'https://en.wikipedia.org/wiki/Claude_Shannon'})
[action] ok: [artifact art:b64e97fde214eb2c, 263047 bytes]

--- iter 2 ---
[memory.read] 1 hit(s)
[perception] [done] Fetch the Wikipedia page for Claude Shannon.
[perception] [open] Extract birth date, death date, and three key contributions to information theory from the fetched page. attach=['art:b64e97fde214eb2c']
[attach] art:b64e97fde214eb2c (263047 bytes)
[decision] ANSWER: Claude Shannon was born on April 30, 1916, and died on February 24, 2001. His three key contributions to information theory include: 1) The development of information entropy as a measure of information content, 2) The establishment of the fundamental limits on data compression and transmission (the source coding and channel coding theorems), and 3) The introduction of the 'bit' as the basic unit of information.

--- iter 3 ---
[memory.read] 1 hit(s)
[perception] [done] Fetch the Wikipedia page for Claude Shannon.
[perception] [done] Extract birth date, death date, and three key contributions to information theory from the fetched page. attach=['art:b64e97fde214eb2c']
[done] all goals satisfied

FINAL:
Claude Shannon was born on April 30, 1916, and died on February 24, 2001. His three key contributions to information theory include: 1) The development of information entropy as a measure of information content, 2) The establishment of the fundamental limits on data compression and transmission (the source coding and channel coding theorems), and 3) The introduction of the 'bit' as the basic unit of information.

--- Query B: Tokyo activities + weather ---

--- iter 1 ---
[memory.read] 0 hit(s)
[perception] [open] Find 3 family-friendly activities in Tokyo.
[perception] [open] Check Saturday's weather forecast for Tokyo.
[perception] [open] Choose the best weather-appropriate activity from the list.
[decision] TOOL_CALL: web_search({'query': 'family-friendly things to do in Tokyo this weekend', 'max_results': 5})
[action] ok: [artifact art:9f8be29339dafd3b, 12376 bytes]

--- iter 2 ---
[memory.read] 1 hit(s)
[perception] [done] Find 3 family-friendly activities in Tokyo. attach=['art:9f8be29339dafd3b']
[perception] [open] Check Saturday's weather forecast for Tokyo.
[perception] [open] Choose the best weather-appropriate activity from the list.
[decision] TOOL_CALL: fetch_url({'url': 'https://wttr.in/Tokyo?format=j1'})
[action] ok: [artifact art:b39d7697f0ae3c6a, 45088 bytes]

--- iter 3 ---
[memory.read] 2 hit(s)
[perception] [done] Find 3 family-friendly activities in Tokyo. attach=['art:9f8be29339dafd3b']
[perception] [done] Check Saturday's weather forecast for Tokyo. attach=['art:b39d7697f0ae3c6a']
[perception] [open] Choose the best weather-appropriate activity from the list. attach=['art:9f8be29339dafd3b', 'art:b39d7697f0ae3c6a']
[attach] art:9f8be29339dafd3b (12376 bytes)
[attach] art:b39d7697f0ae3c6a (45088 bytes)
[decision] ANSWER: Three family-friendly activities in Tokyo this weekend include: 1) The 'Nekoneko Session' JAZZ concert for parents and children (May 16), 2) Visiting the Art Aquarium Museum in Ginza, and 3) Exploring the MIDTOWN OPEN THE PARK 2026 event. Saturday, May 16, is forecast to be sunny with temperatures around 18-19°C. Given the clear, pleasant weather, the 'MIDTOWN OPEN THE PARK 2026' is the most appropriate choice as it offers outdoor picnic spaces and playgrounds, making it ideal for a sunny day.

--- iter 4 ---
[memory.read] 2 hit(s)
[perception] [done] Find 3 family-friendly activities in Tokyo. attach=['art:9f8be29339dafd3b']
[perception] [done] Check Saturday's weather forecast for Tokyo. attach=['art:b39d7697f0ae3c6a']
[perception] [done] Choose the best weather-appropriate activity from the list. attach=['art:9f8be29339dafd3b', 'art:b39d7697f0ae3c6a']
[done] all goals satisfied

FINAL:
Three family-friendly activities in Tokyo this weekend include: 1) The 'Nekoneko Session' JAZZ concert for parents and children (May 16), 2) Visiting the Art Aquarium Museum in Ginza, and 3) Exploring the MIDTOWN OPEN THE PARK 2026 event. Saturday, May 16, is forecast to be sunny with temperatures around 18-19°C. Given the clear, pleasant weather, the 'MIDTOWN OPEN THE PARK 2026' is the most appropriate choice as it offers outdoor picnic spaces and playgrounds, making it ideal for a sunny day.

--- Query C: Mom's birthday (Run 1 — store + reminders) ---

[memory.remember] stored 1 item(s):
  - fact: Mom's birthday is on 15 May 2026.

--- iter 1 ---
[memory.read] 1 hit(s)
[perception] [done] Record mom's birthday in durable memory.
[perception] [open] Create a calendar reminder for two weeks before 15 May 2026.
[perception] [open] Create a calendar reminder for 15 May 2026.
[perception] [open] Confirm all reminders have been set.
[decision] TOOL_CALL: create_file({'path': 'mom_birthday_reminder_1_may_2026.txt', 'content': "Reminder: Mom's birthday is in two weeks on 15 May 2026."})
[action] ok: {"ok": true, "path": "mom_birthday_reminder_1_may_2026.txt", "size_bytes": 56}

--- iter 2 ---
[memory.read] 2 hit(s)
[perception] [done] Record mom's birthday in durable memory.
[perception] [done] Create a calendar reminder for two weeks before 15 May 2026.
[perception] [open] Create a calendar reminder for 15 May 2026.
[perception] [open] Confirm all reminders have been set.
[decision] TOOL_CALL: create_file({'path': 'mom_birthday_15_may_2026.txt', 'content': "Reminder: Mom's birthday is today, 15 May 2026."})
[action] ok: {"ok": true, "path": "mom_birthday_15_may_2026.txt", "size_bytes": 47}

--- iter 3 ---
[memory.read] 3 hit(s)
[perception] [done] Record mom's birthday in durable memory.
[perception] [done] Create a calendar reminder for two weeks before 15 May 2026.
[perception] [done] Create a calendar reminder for 15 May 2026.
[perception] [open] Confirm all reminders have been set.
[decision] ANSWER: I have successfully created both calendar reminders for your mom's birthday on 15 May 2026: one for two weeks prior (1 May 2026) and one for the day of the birthday (15 May 2026).

--- iter 4 ---
[memory.read] 3 hit(s)
[perception] [done] Record mom's birthday in durable memory.
[perception] [done] Create a calendar reminder for two weeks before 15 May 2026.
[perception] [done] Create a calendar reminder for 15 May 2026.
[perception] [done] Confirm all reminders have been set.
[done] all goals satisfied

FINAL:
I have successfully created both calendar reminders for your mom's birthday on 15 May 2026: one for two weeks prior (1 May 2026) and one for the day of the birthday (15 May 2026).

--- Query C: Mom's birthday (Run 2 — recall from memory) ---

--- iter 1 ---
[memory.read] 3 hit(s)
[perception] [done] Answer the user's question about mom's birthday using durable memory.
[decision] ANSWER: Mom's birthday is on 15 May 2026.
[done] all goals satisfied

FINAL:
Mom's birthday is on 15 May 2026.

--- Query D: Asyncio best practices ---

--- iter 1 ---
[memory.read] 0 hit(s)
[perception] [open] Search for 'Python asyncio best practices'
[perception] [open] Fetch the first search result
[perception] [open] Fetch the second search result
[perception] [open] Fetch the third search result
[perception] [open] Synthesize agreed advice from the three fetched results
[decision] TOOL_CALL: web_search({'query': 'Python asyncio best practices', 'max_results': 3})
[action] ok: [artifact art:15ada67761f7599b, 6145 bytes]

--- iter 2 ---
[memory.read] 1 hit(s)
[perception] [done] Search for 'Python asyncio best practices'
[perception] [open] Fetch the first search result
[perception] [open] Fetch the second search result
[perception] [open] Fetch the third search result
[perception] [open] Synthesize agreed advice from the three fetched results attach=['art:15ada67761f7599b']
[decision] TOOL_CALL: fetch_url({'url': 'https://www.shanechang.com/p/python-asyncio-best-practices-pitfalls/'})
[action] ok: [artifact art:9789cf2120a911cd, 8611 bytes]

--- iter 3 ---
[memory.read] 2 hit(s)
[perception] [done] Search for 'Python asyncio best practices'
[perception] [done] Fetch the first search result
[perception] [open] Fetch the second search result
[perception] [open] Fetch the third search result
[perception] [open] Synthesize agreed advice from the three fetched results attach=['art:9789cf2120a911cd']
[decision] TOOL_CALL: fetch_url({'url': 'https://realpython.com/async-io-python/'})
[action] ok: [artifact art:30e2122eff43c08b, 79390 bytes]

--- iter 4 ---
[memory.read] 3 hit(s)
[perception] [done] Search for 'Python asyncio best practices'
[perception] [done] Fetch the first search result
[perception] [done] Fetch the second search result
[perception] [open] Fetch the third search result
[perception] [open] Synthesize agreed advice from the three fetched results attach=['art:9789cf2120a911cd', 'art:30e2122eff43c08b']
[decision] TOOL_CALL: web_search({'query': 'Python asyncio best practices', 'max_results': 3})
[action] ok: [artifact art:15ada67761f7599b, 6145 bytes]

--- iter 5 ---
[memory.read] 3 hit(s)
[perception] [done] Search for 'Python asyncio best practices'
[perception] [done] Fetch the first search result
[perception] [done] Fetch the second search result
[perception] [done] Fetch the third search result
[perception] [open] Synthesize agreed advice from the three fetched results attach=['art:9789cf2120a911cd', 'art:30e2122eff43c08b', 'art:15ada67761f7599b']
[attach] art:9789cf2120a911cd (8611 bytes)
[attach] art:30e2122eff43c08b (79390 bytes)
[attach] art:15ada67761f7599b (6145 bytes)
[decision] ANSWER: Based on the provided sources, here is the agreed-upon advice for using Python's asyncio: 1. Use `asyncio.run()` as the main entry point for your programs to ensure proper event loop setup and cleanup. 2. Do not block the event loop; avoid using blocking calls like `time.sleep()` and instead use non-blocking alternatives like `await asyncio.sleep()`. 3. Always await coroutines to ensure they are executed properly. 4. Use `asyncio.gather()` or `asyncio.create_task()` to run independent operations concurrently. 5. Prefer using async context managers (`async with`) for proper resource management.

--- iter 6 ---
[memory.read] 3 hit(s)
[perception] [done] Search for 'Python asyncio best practices'
[perception] [done] Fetch the first search result
[perception] [done] Fetch the second search result
[perception] [done] Fetch the third search result
[perception] [done] Synthesize agreed advice from the three fetched results attach=['art:9789cf2120a911cd', 'art:30e2122eff43c08b', 'art:15ada67761f7599b']
[done] all goals satisfied

FINAL:
Based on the provided sources, here is the agreed-upon advice for using Python's asyncio: 1. Use `asyncio.run()` as the main entry point for your programs to ensure proper event loop setup and cleanup. 2. Do not block the event loop; avoid using blocking calls like `time.sleep()` and instead use non-blocking alternatives like `await asyncio.sleep()`. 3. Always await coroutines to ensure they are executed properly. 4. Use `asyncio.gather()` or `asyncio.create_task()` to run independent operations concurrently. 5. Prefer using async context managers (`async with`) for proper resource management.
```
