# Assignment
Code: mcp_server.py, needs .env file and must install ddgs, crawl4ai and tavily

### Build an agent that passes all four target queries. The architecture is described above; the implementation is the student's task.

### Required.

- Four code modules with clear separation of concerns: memory.py, perception.py, decision.py, action.py. Plus an orchestrator.py that wires them together in a loop. Plus a schemas.py containing the Pydantic models. Plus the MCP server from earlier sessions.
- All four target queries must produce correct final answers. The expected answers and iteration counts are documented above. Queries that exceed twice the expected iteration count are not considered passing; tune the prompts and the contracts until convergence is within bounds.
- Memory must persist across runs in a file under state/. Query C requires the durable-memory behaviour: run 1 records the fact, run 2 reads it.
- The four cognitive layers must each be backed by typed Pydantic contracts on their inputs and outputs. No free-form dict passing between roles. No regex on LLM output.
- The LLM gateway V3 must be the substrate for every LLM call. No direct calls to provider SDKs.
- The state/ directory must be cleanable between assignment attempts.

### Constraints.

- Pydantic v2 on every boundary.
- uv for Python dependency management and execution. No manual virtualenv activation.
- MCP server stdio transport for tool calls. No reimplementing tool dispatch.
- No third-party agentic frameworks (LangGraph, LangChain, CrewAI). The architecture and the contracts are the assignment.

### Deliverables.

- A GitHub repository containing the code, the state/ directory excluded by .gitignore, and a README that documents how to run each of the four queries.
- The README must include the actual terminal output of each of the four queries, captured from a clean state on the student's own machine.
- Perception and Decision Prompt and Validation JSON of PoP

### Excluded. The assignment is not a summariser, a stock or crypto analyser, or any toy that completes in a single tool call. The four target queries are the assignment.


### Four target queries

1. **Claude Shannon Wikipedia extraction**
   “Fetch the Claude Shannon Wikipedia page and tell me his birth date, death date, and three key contributions to information theory.”
   This is meant to test web fetch + large artifact handling, because the Wikipedia page becomes a large artifact. 

2. **Tokyo weekend activity + weather reasoning**
   “Find three family-friendly things to do in Tokyo this weekend. Check Saturday’s weather forecast there and tell me which one is most appropriate.”
   This tests decomposition into search activities, check weather, then choose the best option based on conditions. 

3. **Memory persistence: mom’s birthday + reminders**
   Run 1: “My mom’s birthday is on 15th May 2026. Remember that and give me a calendar reminder for two weeks before and on the day.”
   Run 2: “When is my mom’s birthday?”
   This tests persistent memory across runs, not just current-loop context. 

4. **AsyncIO / Python best-practices research**
   “Search for Python asyncio best practices. Get the top three results and give me a short numbered list of the advice they agree on.”
   This tests multi-result web research, extraction, comparison, and summarization. 

Rohan also says the assignment is to build an agent system using the discussed architecture — memory, perception, decision, action, Agent 6 loop — and make all four target prompts produce correct final answers, with memory persisted in the `state` folder. 
