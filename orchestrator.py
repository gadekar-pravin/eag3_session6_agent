from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.tree import Tree

from action import Action, ArtifactStore
from decision import Decision
from llm import require_gemini_configured
from llm import usage as llm_usage
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

# Gemini 3.1 Flash Lite approximate pricing (USD per 1M tokens)
_PRICE_PER_M_INPUT = 0.25
_PRICE_PER_M_OUTPUT = 1.50

_con = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


def _label(name: str, color: str, emoji: str = "") -> str:
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}[bold {color}]{name}[/]"


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


def _print_usage_summary() -> None:
    cost = (
        llm_usage.prompt_tokens * _PRICE_PER_M_INPUT / 1_000_000
        + llm_usage.completion_tokens * _PRICE_PER_M_OUTPUT / 1_000_000
    )
    prompt_t = f"{llm_usage.prompt_tokens:,}"
    comp_t = f"{llm_usage.completion_tokens:,}"
    total_t = f"{llm_usage.total_tokens:,}"
    _con.print(
        f"💰 LLM Usage: {llm_usage.call_count} calls · "
        f"{prompt_t} prompt + {comp_t} completion = {total_t} total tokens · "
        f"~${cost:.4f}"
    )


def _print_trace_tree(history: list[HistoryEvent], total_elapsed: float = 0.0) -> None:
    tool_count = sum(1 for e in history if e.kind == "action")
    time_str = f" · {total_elapsed:.1f}s total" if total_elapsed else ""
    header = f"🔄 Execution Trace ({len(history)} iterations · {tool_count} tool call(s){time_str})"
    tree = Tree(header)
    for event in history:
        goal = event.goal_text or ""
        if len(goal) > 60:
            goal = goal[:60] + "…"
        branch = tree.add(f"Iter {event.iter} · {escape(goal)}")
        flow = "🧠 Memory → 👁️ Perception → 🤔 Decision → "
        if event.kind == "action":
            status = "✓" if event.ok else "✗"
            flow += f"⚡ Action({escape(event.tool or '?')}) {status}"
        else:
            flow += "💡 Answer ✓"
        branch.add(flow)
    _con.print(tree)


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
    llm_usage.reset()
    run_start = time.perf_counter()

    memory = Memory(state_dir)
    artifacts = ArtifactStore(state_dir)
    perception = Perception()
    decision = Decision()
    action = Action(artifacts)

    stored = memory.remember(
        MemoryRememberInput(raw_text=query, source="user_query", run_id=run_id)
    ).stored
    if trace and stored:
        _con.print(f"{_label('memory.remember', 'cyan', '🧠')} stored {len(stored)} item(s):")
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
                iter_start = time.perf_counter()

                t0 = time.perf_counter()
                hits = memory.read(MemoryReadInput(query=query, history=history, top_k=12)).hits
                t_memory = time.perf_counter() - t0

                t0 = time.perf_counter()
                obs = perception.observe(
                    PerceptionInput(
                        query=query,
                        hits=hits,
                        history=history,
                        prior_goals=prior_goals,
                        run_id=run_id,
                    )
                ).observation
                t_perception = time.perf_counter() - t0
                prior_goals = obs.goals

                if trace:
                    _con.print()
                    _con.print(Rule(f"iter {iteration}", style="dim"))
                    mem_lbl = _label("memory.read", "cyan", "🧠")
                    _con.print(f"{mem_lbl} {len(hits)} hit(s) [dim]({t_memory:.2f}s)[/]")
                    for i, g in enumerate(prior_goals):
                        icon = "[green]✓[/]" if g.done else "[yellow]○[/]"
                        attach = g.all_attachment_ids()
                        suffix = f" [dim]attach={attach}[/]" if attach else ""
                        lbl = _label("perception", "magenta", "👁️")
                        tsuf = f" [dim]({t_perception:.2f}s)[/]" if i == 0 else ""
                        _con.print(f"{lbl} {icon} {escape(g.text)}{suffix}{tsuf}")

                if obs.all_done:
                    if not any(e.kind == "answer" for e in history):
                        # All goals satisfied from memory — still need Decision
                        # to formulate a user-facing answer.
                        last_goal = obs.goals[-1]
                        t0 = time.perf_counter()
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
                        t_decision = time.perf_counter() - t0
                        if decision_out.is_answer and decision_out.answer:
                            if trace:
                                ans = escape(decision_out.answer[:500])
                                dec_lbl = _label("decision", "yellow", "🤔")
                                _con.print(f"{dec_lbl} ANSWER: {ans} [dim]({t_decision:.2f}s)[/]")
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
                        iter_elapsed = time.perf_counter() - iter_start
                        _con.print(f"⏱️  iter {iteration} total: {iter_elapsed:.2f}s")
                        _con.print("[bold green]✅ all goals satisfied[/]")
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
                            _con.print(f"[dim italic]📎 {aid} ({size} bytes)[/]")

                t0 = time.perf_counter()
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
                t_decision = time.perf_counter() - t0

                if decision_out.is_answer:
                    assert decision_out.answer is not None
                    if trace:
                        ans = escape(decision_out.answer[:500])
                        dec_lbl = _label("decision", "yellow", "🤔")
                        _con.print(f"{dec_lbl} ANSWER: {ans} [dim]({t_decision:.2f}s)[/]")
                    history.append(
                        HistoryEvent(
                            iter=iteration,
                            kind="answer",
                            goal_id=goal.id,
                            goal_text=goal.text,
                            text=decision_out.answer,
                        )
                    )
                    if trace:
                        iter_elapsed = time.perf_counter() - iter_start
                        _con.print(f"⏱️  iter {iteration} total: {iter_elapsed:.2f}s")
                    continue

                assert decision_out.tool_call is not None
                allowed = {t.name for t in mcp_tools}
                if decision_out.tool_call.name not in allowed:
                    if trace:
                        bad = escape(decision_out.tool_call.name)
                        _con.print(f"[red]⚠️  unknown tool '{bad}', skipping[/]")
                    continue
                if trace:
                    tc = decision_out.tool_call
                    name = f"[bold]{escape(tc.name)}[/]"
                    args = f"[dim]{escape(str(tc.arguments))}[/]"
                    dec_lbl = _label("decision", "yellow", "🤔")
                    _con.print(f"{dec_lbl} TOOL_CALL: {name}({args}) [dim]({t_decision:.2f}s)[/]")
                t0 = time.perf_counter()
                action_out = await action.execute(
                    session, ActionInput(tool_call=decision_out.tool_call)
                )
                t_action = time.perf_counter() - t0
                memory.record_outcome(
                    MemoryOutcomeInput(
                        tool_call=decision_out.tool_call,
                        result_text=action_out.descriptor or action_out.result_text,
                        ok=action_out.ok,
                        artifact_id=action_out.artifact_id,
                        run_id=run_id,
                        goal_id=goal.id,
                    )
                )
                if trace:
                    status_tag = "[green]ok[/]" if action_out.ok else "[red]error[/]"
                    desc = escape(action_out.descriptor[:700])
                    act_lbl = _label("action", "blue", "⚡")
                    _con.print(f"{act_lbl} {status_tag}: {desc} [dim]({t_action:.2f}s)[/]")
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
                if trace:
                    iter_elapsed = time.perf_counter() - iter_start
                    _con.print(f"⏱️  iter {iteration} total: {iter_elapsed:.2f}s")
            else:
                if trace:
                    _con.print(f"[bold red]🛑 max iterations reached: {max_iterations}[/]")

    answer = final_answer_from(history)
    if trace:
        _con.print()
        _con.print(Panel(escape(answer), title="✨ FINAL", border_style="green"))
        total_elapsed = time.perf_counter() - run_start
        if history:
            _print_trace_tree(history, total_elapsed)
        _con.print(f"⏱️  total: {total_elapsed:.2f}s")
        if llm_usage.call_count > 0:
            _print_usage_summary()
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
