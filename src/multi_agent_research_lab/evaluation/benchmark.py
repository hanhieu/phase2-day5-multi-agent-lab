"""Benchmark utilities for single-agent vs multi-agent comparison."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter

from multi_agent_research_lab.core.schemas import BenchmarkMetrics
from multi_agent_research_lab.core.state import ResearchState

logger = logging.getLogger(__name__)

Runner = Callable[[str], ResearchState]


def _extract_total_cost(state: ResearchState) -> float:
    """Sum cost_usd from all trace events that carry it."""

    total = 0.0
    for event in state.trace:
        payload = event.get("payload", {})
        cost = payload.get("cost_usd")
        if cost is not None:
            total += cost
    return total


def _citation_coverage(state: ResearchState) -> float:
    """Ratio of sources that appear as citations in the final answer (0.0–1.0).

    A source is considered cited if its title (or a significant keyword from
    its title) appears in the final answer text.
    """

    if not state.sources or not state.final_answer:
        return 0.0

    answer_lower = state.final_answer.lower()
    cited = 0
    for src in state.sources:
        # Check title keywords (words > 4 chars) appear in answer
        keywords = [w for w in re.split(r"\W+", src.title.lower()) if len(w) > 4]
        if any(kw in answer_lower for kw in keywords):
            cited += 1
    return cited / len(state.sources)


def _estimate_quality(state: ResearchState) -> float:
    """Heuristic quality score (0-10) based on output completeness.

    Criteria:
    - final_answer present and >= 200 chars  → +4
    - research_notes present                 → +2
    - analysis_notes present                 → +2
    - at least 1 source cited                → +1
    - no errors                              → +1
    """

    score = 0.0
    if state.final_answer and len(state.final_answer) >= 200:
        score += 4
    if state.research_notes:
        score += 2
    if state.analysis_notes:
        score += 2
    if state.sources:
        score += 1
    if not state.errors:
        score += 1
    return score


def run_benchmark(
    run_name: str,
    query: str,
    runner: Runner,
) -> tuple[ResearchState, BenchmarkMetrics]:
    """Measure latency, cost, quality, citation coverage; return state + metrics."""

    logger.info("Benchmark '%s' starting for query: %s", run_name, query)
    started = perf_counter()
    try:
        state = runner(query)
        failed = False
    except Exception as exc:  # noqa: BLE001
        logger.error("Benchmark '%s' runner raised: %s", run_name, exc)
        from multi_agent_research_lab.core.schemas import ResearchQuery  # noqa: PLC0415

        state = ResearchState(request=ResearchQuery(query=query))
        state.errors.append(str(exc))
        failed = True

    latency = perf_counter() - started
    cost = _extract_total_cost(state)
    quality = 0.0 if failed else _estimate_quality(state)
    citation_cov = _citation_coverage(state)

    notes = (
        "FAILED" if failed else f"routes={state.route_history} | citation_cov={citation_cov:.0%}"
    )

    metrics = BenchmarkMetrics(
        run_name=run_name,
        latency_seconds=latency,
        estimated_cost_usd=cost if cost > 0 else None,
        quality_score=quality,
        notes=notes,
    )
    logger.info(
        "Benchmark '%s' done: latency=%.2fs cost=$%.6f quality=%.1f citation_cov=%.0f%%",
        run_name,
        latency,
        cost,
        quality,
        citation_cov * 100,
    )
    return state, metrics


# ---------------------------------------------------------------------------
# Multi-query benchmark
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    """Result for a single query in a multi-query run."""

    query: str
    metrics: BenchmarkMetrics
    failed: bool


@dataclass
class MultiQuerySummary:
    """Aggregate summary across all queries for one runner."""

    run_name: str
    results: list[QueryResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if r.failed)

    @property
    def failure_rate(self) -> float:
        return self.failures / self.total if self.total else 0.0

    @property
    def avg_latency(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.metrics.latency_seconds for r in self.results) / self.total

    @property
    def total_cost(self) -> float:
        return sum(r.metrics.estimated_cost_usd or 0.0 for r in self.results)

    @property
    def avg_quality(self) -> float:
        scores = [
            r.metrics.quality_score
            for r in self.results
            if r.metrics.quality_score is not None
        ]
        return sum(scores) / len(scores) if scores else 0.0


def run_multi_query_benchmark(
    run_name: str,
    queries: list[str],
    runner: Runner,
) -> MultiQuerySummary:
    """Run *runner* against every query and collect per-query + aggregate metrics."""

    summary = MultiQuerySummary(run_name=run_name)
    for i, query in enumerate(queries, 1):
        logger.info(
            "Multi-query benchmark '%s' [%d/%d]: %s",
            run_name,
            i,
            len(queries),
            query,
        )
        state, metrics = run_benchmark(f"{run_name}[q{i}]", query, runner)
        failed = bool(state.errors) or state.final_answer is None
        summary.results.append(QueryResult(query=query, metrics=metrics, failed=failed))

    logger.info(
        "Multi-query '%s' done: %d/%d failed (%.0f%%) avg_latency=%.1fs total_cost=$%.4f",
        run_name,
        summary.failures,
        summary.total,
        summary.failure_rate * 100,
        summary.avg_latency,
        summary.total_cost,
    )
    return summary
