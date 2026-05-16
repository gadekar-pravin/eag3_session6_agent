from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule

from action import Action, ArtifactStore
from decision import Decision
from llm import require_gemini_configured
from memory import Memory
from perception import Perception
from schemas import (
    ActionInput,
    DecisionInput,
    HistoryEvent,
    MemoryOutcomeInput,
    MemoryReadInput,
    MemoryRememberInput,
    PerceptionInput,
    ToolSpec,
)

MAX_ITERATIONS = 14

_con = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


def _label(name: str, color: str) -> str:
    return f"[bold {color}]{name}[/]"


def clean_state(repo_dir: Path) -> None:
    for name in ["state", "sandbox", "usage.json"]:
        target = repo_dir / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def final_answer_from(history: list[HistoryEvent]) -> str:
    for event in reversed(history):
        if event.kind == "answer" and event.text:
            return event.text
    return "No final answer was produced before the loop ended."


def tool_specs_from_mcp(list_tools_result) -> list[ToolSpec]:
    tools = getattr(list_tools_result, "tools", list_tools_result)
    specs: list[ToolSpec] = []
    for tool in tools:
        name = getattr(tool, "name", "")
        description = getattr(tool, "description", "") or ""
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        specs.append(ToolSpec(name=name, description=description, input_schema=schema))
    return specs


async def run(
    query: str,
    *,
    state_dir: str | Path = "state",
    max_iterations: int = MAX_ITERATIONS,
    trace: bool = True,
) -> str:
    repo_dir = Path(__file__).resolve().parent
    run_id = uuid4().hex[:8]
    require_gemini_configured()

    memory = Memory(state_dir)
    artifacts = ArtifactStore(state_dir)
    perception = Perception()
    decision = Decision()
    action = Action(artifacts)

    stored = memory.remember(
        MemoryRememberInput(raw_text=query, source="user_query", run_id=run_id)
    ).stored
    if trace and stored:
        _con.print(f"{_label('memory.remember', 'cyan')} stored {len(stored)} item(s):")
        for item in stored:
            _con.print(f"  [dim]-[/] {escape(item.kind)}: {escape(item.descriptor)}")

    history: list[HistoryEvent] = []
    prior_goals = []

    server = repo_dir / "mcp_server.py"
    server_params = StdioServerParameters(command=sys.executable, args=[str(server)])

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            mcp_tools = tool_specs_from_mcp(await session.list_tools())

            for iteration in range(1, max_iterations + 1):
                hits = memory.read(MemoryReadInput(query=query, history=history, top_k=12)).hits
                obs = perception.observe(
                    PerceptionInput(
                        query=query,
                        hits=hits,
                        history=history,
                        prior_goals=prior_goals,
                        run_id=run_id,
                    )
                ).observation
                prior_goals = obs.goals

                if trace:
                    _con.print()
                    _con.print(Rule(f"iter {iteration}", style="dim"))
                    _con.print(f"{_label('memory.read', 'cyan')} {len(hits)} hit(s)")
                    for g in prior_goals:
                        icon = "[green]✓[/]" if g.done else "[yellow]○[/]"
                        attach = g.all_attachment_ids()
                        suffix = f" [dim]attach={attach}[/]" if attach else ""
                        lbl = _label("perception", "magenta")
                        _con.print(f"{lbl} {icon} {escape(g.text)}{suffix}")

                if obs.all_done:
                    if not any(e.kind == "answer" for e in history):
                        # All goals satisfied from memory — still need Decision
                        # to formulate a user-facing answer.
                        last_goal = obs.goals[-1]
                        decision_out = decision.next_step(
                            DecisionInput(
                                query=query,
                                goal=last_goal,
                                hits=hits,
                                attached_artifacts={},
                                history=history,
                                tools=mcp_tools,
                            )
                        )
                        if decision_out.is_answer and decision_out.answer:
                            if trace:
                                ans = escape(decision_out.answer[:500])
                                _con.print(f"{_label('decision', 'yellow')} ANSWER: {ans}")
                            history.append(
                                HistoryEvent(
                                    iter=iteration,
                                    kind="answer",
                                    goal_id=last_goal.id,
                                    goal_text=last_goal.text,
                                    text=decision_out.answer,
                                )
                            )
                    if trace:
                        _con.print("[bold green]\\[done] all goals satisfied[/]")
                    break

                goal = obs.next_unfinished()
                if goal is None:
                    break

                attached: dict[str, str] = {}
                for artifact_id in goal.all_attachment_ids():
                    if artifacts.exists(artifact_id):
                        attached[artifact_id] = artifacts.get_text(artifact_id)
                        if trace:
                            size = len(attached[artifact_id].encode("utf-8"))
                            aid = escape(artifact_id)
                            _con.print(f"[dim italic]\\[attach] {aid} ({size} bytes)[/]")

                decision_out = decision.next_step(
                    DecisionInput(
                        query=query,
                        goal=goal,
                        hits=hits,
                        attached_artifacts=attached,
                        history=history,
                        tools=mcp_tools,
                    )
                )

                if decision_out.is_answer:
                    assert decision_out.answer is not None
                    if trace:
                        ans = escape(decision_out.answer[:500])
                        _con.print(f"{_label('decision', 'yellow')} ANSWER: {ans}")
                    history.append(
                        HistoryEvent(
                            iter=iteration,
                            kind="answer",
                            goal_id=goal.id,
                            goal_text=goal.text,
                            text=decision_out.answer,
                        )
                    )
                    continue

                assert decision_out.tool_call is not None
                if trace:
                    tc = decision_out.tool_call
                    name = f"[bold]{escape(tc.name)}[/]"
                    args = f"[dim]{escape(str(tc.arguments))}[/]"
                    _con.print(f"{_label('decision', 'yellow')} TOOL_CALL: {name}({args})")
                action_out = await action.execute(
                    session, ActionInput(tool_call=decision_out.tool_call)
                )
                memory.record_outcome(
                    MemoryOutcomeInput(
                        tool_call=decision_out.tool_call,
                        result_text=action_out.descriptor or action_out.result_text,
                        artifact_id=action_out.artifact_id,
                        run_id=run_id,
                        goal_id=goal.id,
                    )
                )
                if trace:
                    status_tag = "[green]ok[/]" if action_out.ok else "[red]error[/]"
                    desc = escape(action_out.descriptor[:700])
                    _con.print(f"{_label('action', 'blue')} {status_tag}: {desc}")
                history.append(
                    HistoryEvent(
                        iter=iteration,
                        kind="action",
                        goal_id=goal.id,
                        goal_text=goal.text,
                        tool=decision_out.tool_call.name,
                        arguments=decision_out.tool_call.arguments,
                        result_descriptor=action_out.descriptor[:1000],
                        result_text=(
                            action_out.result_text
                            if len(action_out.result_text.encode("utf-8")) <= 4096
                            else ""
                        ),
                        artifact_id=action_out.artifact_id,
                        ok=action_out.ok,
                    )
                )
            else:
                if trace:
                    _con.print(f"[bold red]\\[stop] max iterations reached: {max_iterations}[/]")

    answer = final_answer_from(history)
    if trace:
        _con.print()
        _con.print(Panel(escape(answer), title="FINAL", border_style="green"))
    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EAG3 Session 6 agent loop.")
    parser.add_argument("query", nargs="+", help="Target query to run")
    parser.add_argument(
        "--state-dir",
        default="state",
        help="Directory for durable memory and artifacts",
    )
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete state/, sandbox/ and usage.json before running",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print the final answer")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parent
    if args.clean:
        clean_state(repo_dir)

    query = " ".join(args.query)
    try:
        answer = asyncio.run(
            run(
                query,
                state_dir=args.state_dir,
                max_iterations=args.max_iterations,
                trace=not args.quiet,
            )
        )
    except RuntimeError as exc:
        if "GEMINI_API_KEY" not in str(exc):
            raise
        _err.print(f"[bold red]ERROR:[/] {escape(str(exc))}")
        raise SystemExit(1) from None
    if args.quiet:
        print(answer)


if __name__ == "__main__":
    main()
