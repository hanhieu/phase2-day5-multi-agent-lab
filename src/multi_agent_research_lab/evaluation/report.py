"""Benchmark report rendering."""

from multi_agent_research_lab.core.schemas import BenchmarkMetrics


def render_markdown_report(metrics: list[BenchmarkMetrics]) -> str:
    """Render benchmark metrics to a rich markdown report with analysis."""

    header = [
        "# Benchmark Report",
        "",
        "## Metrics Table",
        "",
        "| Run | Latency (s) | Cost (USD) | Quality (0-10) | Notes |",
        "|---|---:|---:|---:|---|",
    ]
    rows = []
    for item in metrics:
        cost = "" if item.estimated_cost_usd is None else f"{item.estimated_cost_usd:.4f}"
        quality = "" if item.quality_score is None else f"{item.quality_score:.1f}"
        rows.append(
            f"| {item.run_name} | {item.latency_seconds:.2f} | {cost} | {quality} | {item.notes} |"
        )

    # Analysis section
    analysis: list[str] = ["", "## Analysis", ""]
    if len(metrics) >= 2:
        a, b = metrics[0], metrics[1]
        latency_ratio = b.latency_seconds / a.latency_seconds if a.latency_seconds else 0
        cost_ratio = (b.estimated_cost_usd or 0) / (a.estimated_cost_usd or 1)
        quality_delta = (b.quality_score or 0) - (a.quality_score or 0)
        winner = (
            "neither" if quality_delta == 0 else (b.run_name if quality_delta > 0 else a.run_name)
        )
        analysis += [
            f"- **Latency**: `{b.run_name}` is {latency_ratio:.1f}× "
            f"{'slower' if latency_ratio > 1 else 'faster'} than `{a.run_name}`.",
            f"- **Cost**: `{b.run_name}` costs {cost_ratio:.1f}× "
            f"{'more' if cost_ratio > 1 else 'less'} than `{a.run_name}`.",
            f"- **Quality delta**: {quality_delta:+.1f} points in favour of `{winner}`.",
            "",
        ]

    failure_section = [
        "## Failure Modes & Fixes",
        "",
        "| Failure mode | Observed in | Fix applied |",
        "|---|---|---|",
        "| Hallucination (wrong definition) | baseline | "
        "Multi-agent grounds LLM with retrieved sources |",
        "| API retry / transient timeout | baseline (run 2) | "
        "tenacity retry with exponential backoff |",
        "| Tavily key trailing chars | search_client | Trim key, fallback to mock on auth error |",
        "| LangGraph rejects Pydantic model | workflow | "
        "Serialize ResearchState ↔ dict at node boundaries |",
        "",
    ]

    return "\n".join(header + rows + analysis + failure_section)


def render_multi_query_report(
    summaries: "list[MultiQuerySummary]",  # noqa: F821 — imported below
) -> str:
    """Render a multi-query benchmark report comparing two runners."""


    lines = [
        "# Multi-Query Benchmark Report",
        "",
        "## Summary",
        "",
        "| Runner | Queries | Failures | Failure Rate | Avg Latency (s) "
        "| Total Cost (USD) | Avg Quality |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            f"| {s.run_name} "
            f"| {s.total} "
            f"| {s.failures} "
            f"| {s.failure_rate:.0%} "
            f"| {s.avg_latency:.1f} "
            f"| {s.total_cost:.4f} "
            f"| {s.avg_quality:.1f} |"
        )

    lines += ["", "## Per-Query Results", ""]

    # Collect all unique queries in order
    all_queries: list[str] = []
    seen: set[str] = set()
    for s in summaries:
        for r in s.results:
            if r.query not in seen:
                all_queries.append(r.query)
                seen.add(r.query)

    # Build lookup: run_name → query → QueryResult
    lookup: dict[str, dict[str, QueryResult]] = {}  # noqa: F821
    for s in summaries:
        lookup[s.run_name] = {r.query: r for r in s.results}

    # Header row
    runner_names = [s.run_name for s in summaries]
    col_headers = " | ".join(
        f"Latency | Quality | Failed ({n})" for n in runner_names
    )
    sep = " | ".join(["---:|---:|---:" for _ in runner_names])
    lines.append(f"| # | Query | {col_headers} |")
    lines.append(f"|---:|---|{sep}|")

    for i, query in enumerate(all_queries, 1):
        short_q = query[:60] + "…" if len(query) > 60 else query
        row = f"| {i} | {short_q} |"
        for s in summaries:
            r = lookup[s.run_name].get(query)
            if r:
                lat = f"{r.metrics.latency_seconds:.1f}s"
                qs = r.metrics.quality_score
                qual = f"{qs:.0f}" if qs is not None else "-"
                fail = "❌" if r.failed else "✅"
                row += f" {lat} | {qual} | {fail} |"
            else:
                row += " - | - | - |"
        lines.append(row)

    lines += [
        "",
        "## Failure Rate Comparison",
        "",
    ]
    for s in summaries:
        lines.append(
            f"- **{s.run_name}**: {s.failures}/{s.total} queries failed "
            f"({s.failure_rate:.0%})"
        )

    lines.append("")
    return "\n".join(lines)
