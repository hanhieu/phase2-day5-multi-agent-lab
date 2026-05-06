"""Command-line entrypoint for the lab starter."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel

from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.errors import StudentTodoError
from multi_agent_research_lab.core.schemas import ResearchQuery
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.evaluation.benchmark import run_benchmark, run_multi_query_benchmark
from multi_agent_research_lab.evaluation.report import (
    render_markdown_report,
    render_multi_query_report,
)
from multi_agent_research_lab.graph.workflow import MultiAgentWorkflow
from multi_agent_research_lab.observability.logging import configure_logging
from multi_agent_research_lab.observability.tracing import export_trace_json
from multi_agent_research_lab.services.llm_client import LLMClient
from multi_agent_research_lab.services.storage import LocalArtifactStore

app = typer.Typer(help="Multi-Agent Research Lab CLI")
console = Console()


def _init() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)


def _save_run(run_type: str, state: ResearchState) -> None:
    """Persist every field of a completed run to reports/<run_type>/<timestamp>/."""

    store = LocalArtifactStore()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{run_type}/{ts}"

    # ── Full state as JSON (machine-readable) ──────────────────────────────
    store.write_text(f"{base}/state.json", state.model_dump_json(indent=2))

    # ── Human-readable markdown report ────────────────────────────────────
    lines: list[str] = [
        f"# Run: {run_type}  —  {ts}",
        "",
        f"**Query:** {state.request.query}",
        f"**Iterations:** {state.iteration}",
        f"**Route history:** {' → '.join(state.route_history)}",
        "",
    ]

    if state.sources:
        lines += ["## Sources", ""]
        for i, src in enumerate(state.sources, 1):
            url_part = f" — {src.url}" if src.url else ""
            lines.append(f"{i}. **{src.title}**{url_part}")
            lines.append(f"   > {src.snippet[:200]}{'…' if len(src.snippet) > 200 else ''}")
            lines.append("")

    if state.research_notes:
        lines += ["## Research Notes", "", state.research_notes, ""]

    if state.analysis_notes:
        lines += ["## Analysis Notes", "", state.analysis_notes, ""]

    if state.final_answer:
        lines += ["## Final Answer", "", state.final_answer, ""]

    if state.errors:
        lines += ["## Errors", ""]
        for err in state.errors:
            lines.append(f"- {err}")
        lines.append("")

    if state.trace:
        lines += ["## Trace", "", "```json", json.dumps(state.trace, indent=2), "```", ""]

    md = "\n".join(lines)
    path = store.write_text(f"{base}/run_report.md", md)

    # Export trace as separate JSON file
    export_trace_json(state.trace, path.parent / "trace.json")

    console.print(f"[dim]Run saved → {path.parent}[/dim]")


# ---------------------------------------------------------------------------
# Baseline command — single LLM call, no multi-agent orchestration
# ---------------------------------------------------------------------------

_BASELINE_SYSTEM = """\
You are a research assistant. Answer the user's query thoroughly in 400-600 words.
Include key facts, cite any well-known sources you know, and end with a brief summary.
"""


def _run_baseline(query: str) -> ResearchState:
    """Single-agent runner used by both the CLI command and the benchmark."""

    llm = LLMClient()
    response = llm.complete(_BASELINE_SYSTEM, query)
    state = ResearchState(request=ResearchQuery(query=query))
    state.final_answer = response.content
    state.add_trace_event(
        "baseline_llm",
        {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": response.cost_usd,
        },
    )
    return state


@app.command()
def baseline(
    query: Annotated[str, typer.Option("--query", "-q", help="Research query")],
) -> None:
    """Run a single-agent baseline (one LLM call, no orchestration)."""

    _init()
    state = _run_baseline(query)
    console.print(Panel.fit(state.final_answer or "", title="Single-Agent Baseline"))
    _save_run("baseline", state)


# ---------------------------------------------------------------------------
# Multi-agent command
# ---------------------------------------------------------------------------


def _run_multi_agent(query: str) -> ResearchState:
    """Multi-agent runner used by both the CLI command and the benchmark."""

    state = ResearchState(request=ResearchQuery(query=query))
    workflow = MultiAgentWorkflow()
    return workflow.run(state)


@app.command("multi-agent")
def multi_agent(
    query: Annotated[str, typer.Option("--query", "-q", help="Research query")],
) -> None:
    """Run the full multi-agent workflow (Supervisor → Researcher → Analyst → Writer)."""

    _init()
    state = ResearchState(request=ResearchQuery(query=query))
    workflow = MultiAgentWorkflow()
    try:
        result = workflow.run(state)
    except StudentTodoError as exc:
        console.print(Panel.fit(str(exc), title="Expected TODO", style="yellow"))
        raise typer.Exit(code=2) from exc

    console.print(Panel.fit(result.final_answer or "(no answer)", title="Multi-Agent Result"))
    console.print(f"\n[dim]Route history: {result.route_history}[/dim]")
    _save_run("multi-agent", result)


# ---------------------------------------------------------------------------
# Benchmark command — runs both and saves report
# ---------------------------------------------------------------------------


@app.command()
def benchmark(
    query: Annotated[
        str,
        typer.Option(
            "--query",
            "-q",
            help="Research query to benchmark",
        ),
    ] = "Research GraphRAG state-of-the-art and write a 500-word summary",
) -> None:
    """Benchmark single-agent baseline vs multi-agent workflow and save a report."""

    _init()
    console.print("[bold]Running benchmark…[/bold]")

    console.print("  [1/2] Single-agent baseline…")
    baseline_state, baseline_metrics = run_benchmark("baseline", query, _run_baseline)
    _save_run("baseline", baseline_state)

    console.print("  [2/2] Multi-agent workflow…")
    multi_state, multi_metrics = run_benchmark("multi-agent", query, _run_multi_agent)
    _save_run("multi-agent", multi_state)

    report_md = render_markdown_report([baseline_metrics, multi_metrics])

    store = LocalArtifactStore()
    path = store.write_text("benchmark_report.md", report_md)
    console.print(f"\n[green]Report saved to {path}[/green]")
    console.print(report_md)


# ---------------------------------------------------------------------------
# benchmark-full command — multi-query from configs/lab_default.yaml
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = Path("configs/lab_default.yaml")


def _load_queries(config_path: Path) -> list[str]:
    """Load benchmark queries from the YAML config file."""

    with config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    queries: list[str] = cfg.get("benchmark", {}).get("queries", [])
    if not queries:
        raise ValueError(f"No benchmark.queries found in {config_path}")
    return queries


@app.command("benchmark-full")
def benchmark_full(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML config with benchmark queries"),
    ] = _DEFAULT_CONFIG,
) -> None:
    """Run baseline vs multi-agent across ALL queries in the config file.

    Measures per-query latency, cost, quality, and computes aggregate
    failure rate across the full query set.
    """

    _init()
    queries = _load_queries(config)
    console.print(
        f"[bold]Running full benchmark — {len(queries)} queries × 2 runners[/bold]"
    )
    console.print(f"[dim]Config: {config}[/dim]\n")

    # ── Baseline ──────────────────────────────────────────────────────────
    console.print("[bold cyan]Runner 1/2: baseline[/bold cyan]")
    baseline_summary = run_multi_query_benchmark("baseline", queries, _run_baseline)
    for r in baseline_summary.results:
        status = "❌ FAILED" if r.failed else "✅"
        console.print(
            f"  {status}  [{r.metrics.latency_seconds:.1f}s / "
            f"${r.metrics.estimated_cost_usd or 0:.4f}]  {r.query[:70]}"
        )

    console.print()

    # ── Multi-agent ───────────────────────────────────────────────────────
    console.print("[bold cyan]Runner 2/2: multi-agent[/bold cyan]")
    multi_summary = run_multi_query_benchmark("multi-agent", queries, _run_multi_agent)
    for r in multi_summary.results:
        status = "❌ FAILED" if r.failed else "✅"
        console.print(
            f"  {status}  [{r.metrics.latency_seconds:.1f}s / "
            f"${r.metrics.estimated_cost_usd or 0:.4f}]  {r.query[:70]}"
        )

    console.print()

    # ── Report ────────────────────────────────────────────────────────────
    report_md = render_multi_query_report([baseline_summary, multi_summary])
    store = LocalArtifactStore()
    path = store.write_text("multi_query_benchmark_report.md", report_md)
    console.print(f"[green]Report saved to {path}[/green]\n")
    console.print(report_md)


if __name__ == "__main__":
    app()
