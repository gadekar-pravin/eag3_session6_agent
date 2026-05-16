# Python agent loop walkthrough

This file is a command-line runner for an iterative agent loop. At a high level, it:

1. Takes a user query from the command line or from `run(query)`.
2. Checks that Gemini configuration is available.
3. Starts an MCP server as a subprocess over stdio.
4. Repeatedly cycles through memory, perception, decision, and action until the task is answered, all goals are complete, or the maximum iteration limit is reached.
5. Prints a rich execution trace and returns the final answer.

---

## Big-picture architecture

```mermaid
flowchart TD
    A[User query] --> B[main parses CLI args]
    B --> C{--clean provided?}
    C -- yes --> D[clean_state deletes state, sandbox, usage.json]
    C -- no --> E[Build query string]
    D --> E
    E --> F[asyncio.run run]

    F --> G[run initializes components]
    G --> G1[Memory]
    G --> G2[ArtifactStore]
    G --> G3[Perception]
    G --> G4[Decision]
    G --> G5[Action]

    G --> H[Remember user query]
    H --> I[Start MCP server via stdio_client]
    I --> J[Initialize MCP ClientSession]
    J --> K[List MCP tools]
    K --> L[Convert MCP tools to ToolSpec]
    L --> M[Iteration loop]

    M --> N[Memory.read: retrieve relevant past hits]
    N --> O[Perception.observe: infer goals and completion]
    O --> P{All goals done?}

    P -- yes --> Q{Already have answer in history?}
    Q -- no --> R[Decision.next_step formulates final answer]
    R --> S[Append answer event]
    Q -- yes --> T[Break loop]
    S --> T

    P -- no --> U[Pick next unfinished goal]
    U --> V[Attach artifact text if needed]
    V --> W[Decision.next_step]
    W --> X{Decision is answer?}

    X -- yes --> Y[Append answer event]
    Y --> M

    X -- no, tool call --> Z[Action.execute MCP tool call]
    Z --> AA[Memory.record_outcome]
    AA --> AB[Append action event]
    AB --> M

    M --> AC{Max iterations reached?}
    AC -- yes --> AD[Print max-iteration warning]
    T --> AE[final_answer_from history]
    AD --> AE
    AE --> AF[Print final answer and trace tree]
    AF --> AG[Return answer]
```

---

## The core loop in plain English

The most important function is `run(...)`. It performs a repeated agent cycle:

```mermaid
flowchart LR
    M[Memory] --> P[Perception]
    P --> D[Decision]
    D --> A[Action]
    A --> M
    D --> Ans[Final answer]
```

Each iteration follows this sequence:

1. **Memory**: search stored memory for relevant context.
2. **Perception**: turn the query, memory hits, history, and prior goals into an observation containing goals.
3. **Decision**: decide whether to answer now or call a tool.
4. **Action**: if a tool is chosen, execute it through the MCP session.
5. **Memory outcome**: record what happened so later iterations can use it.
6. **History**: append either an `action` event or an `answer` event.

The loop stops when:

* Perception says all goals are done.
* A final answer can be extracted from history.
* The iteration limit is reached.
* There is no unfinished goal.

---

## Important functions and what they do

### `_label(name, color, emoji="")`

Builds a Rich markup label like a colored heading with an optional emoji. This is only for nice terminal output.

### `clean_state(repo_dir)`

Deletes local runtime state:

* `state/`
* `sandbox/`
* `usage.json`

It is triggered by the CLI flag `--clean`.

### `final_answer_from(history)`

Walks backward through the history and returns the latest event whose kind is `"answer"`. If no answer was produced, it returns a fallback message.

### `tool_specs_from_mcp(list_tools_result)`

Normalizes MCP tool metadata into local `ToolSpec` objects. It handles both possible shapes:

* an object with `.tools`
* a raw iterable of tools

### `_print_trace_tree(history, total_elapsed=0.0)`

Builds a Rich tree showing each iteration, the goal, and whether the iteration ended with an action/tool call or an answer.

### `run(query, state_dir="state", max_iterations=MAX_ITERATIONS, trace=True)`

The main async orchestration function. It initializes the agent components, starts the MCP server, loops through memory/perception/decision/action, then returns the final answer.

### `main()`

The CLI entrypoint. It parses arguments, optionally cleans state, joins positional arguments into a query string, runs the async loop, and handles missing Gemini API configuration errors.

---

## Data flow diagram

```mermaid
flowchart TB
    Query[query string] --> Remember[Memory.remember]
    Remember --> State[(state_dir)]

    Query --> Read[Memory.read]
    State --> Read
    History[(history list)] --> Read
    Read --> Hits[hits]

    Query --> Observe[Perception.observe]
    Hits --> Observe
    History --> Observe
    PriorGoals[(prior_goals)] --> Observe
    Observe --> Goals[goals]
    Goals --> PriorGoals

    Goals --> DecisionStep[Decision.next_step]
    Hits --> DecisionStep
    History --> DecisionStep
    Tools[MCP tool specs] --> DecisionStep
    Artifacts[(ArtifactStore)] --> Attached[attached artifact text]
    Attached --> DecisionStep

    DecisionStep -->|answer| AnswerEvent[HistoryEvent kind=answer]
    AnswerEvent --> History

    DecisionStep -->|tool_call| Execute[Action.execute]
    Session[MCP ClientSession] --> Execute
    Execute --> ActionOut[action output]
    ActionOut --> Record[Memory.record_outcome]
    Record --> State
    ActionOut --> ActionEvent[HistoryEvent kind=action]
    ActionEvent --> History

    History --> Final[final_answer_from]
```

---

## How the agent decides what to do next

The decision step receives:

* the original `query`
* the current unfinished `goal`
* memory `hits`
* any `attached_artifacts`
* the full `history`
* available MCP `tools`

It can return one of two things:

```mermaid
flowchart TD
    A[Decision.next_step] --> B{is_answer?}
    B -- yes --> C[Use decision_out.answer]
    C --> D[Append HistoryEvent kind=answer]
    B -- no --> E[Use decision_out.tool_call]
    E --> F[Action.execute]
    F --> G[Record tool result in memory]
    G --> H[Append HistoryEvent kind=action]
```

So `Decision` acts like the controller: it chooses whether the agent should speak or use a tool.

---

## Error and exit behavior

The CLI catches `RuntimeError` only to handle the specific case where Gemini configuration is missing:

```mermaid
flowchart TD
    A[main calls asyncio.run run] --> B{RuntimeError?}
    B -- no --> C[Continue normally]
    B -- yes --> D{Message contains GEMINI_API_KEY?}
    D -- no --> E[Re-raise exception]
    D -- yes --> F[Print friendly ERROR]
    F --> G[Exit with code 1]
```

If `--quiet` is used, the program suppresses the trace and prints only the final answer.

---

## Mental model

Think of this file as the **outer runtime shell** for an agent:

* `Memory` remembers and retrieves context.
* `Perception` turns context into goals.
* `Decision` chooses answer vs. tool call.
* `Action` executes tool calls through MCP.
* `ArtifactStore` stores and retrieves generated artifacts.
* `HistoryEvent` records what happened each iteration.
* Rich console output makes the process visible to the user.

The file itself does not contain the intelligence of the agent. It coordinates specialized modules that are imported from nearby files: `memory`, `perception`, `decision`, `action`, and `schemas`.

---

## Pseudocode summary

```python
remember(query)
start_mcp_server()
list_available_tools()

for iteration in range(max_iterations):
    hits = memory.read(query, history)
    observation = perception.observe(query, hits, history, prior_goals)

    if observation.all_done:
        if no answer yet:
            answer = decision.next_step(...)
            history.append(answer)
        break

    goal = observation.next_unfinished()
    attached_artifacts = load_artifacts_referenced_by_goal(goal)

    decision = decision.next_step(query, goal, hits, attached_artifacts, history, tools)

    if decision.is_answer:
        history.append(answer_event)
    else:
        result = action.execute(decision.tool_call)
        memory.record_outcome(result)
        history.append(action_event)

return latest_answer_from(history)
```

---

## Key thing to notice

The loop is not simply “call an LLM once.” It is an **iterative planning and tool-use loop**. Each pass can update memory and history, which changes what the next pass sees. That is why the file keeps careful records of goals, tool outputs, artifacts, timings, and trace output.
