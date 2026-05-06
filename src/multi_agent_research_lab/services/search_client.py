"""Search client abstraction for ResearcherAgent.

Uses Tavily when TAVILY_API_KEY is set; falls back to a curated mock otherwise.
"""

from __future__ import annotations

import logging

from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.schemas import SourceDocument

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data — used when no real search key is available
# ---------------------------------------------------------------------------
_MOCK_SOURCES: list[SourceDocument] = [
    SourceDocument(
        title="LangGraph: Building Stateful Multi-Actor Applications",
        url="https://langchain-ai.github.io/langgraph/concepts/",
        snippet=(
            "LangGraph is a library for building stateful, multi-actor applications with LLMs. "
            "It models agent workflows as directed graphs where nodes are agents or tools and "
            "edges represent transitions. Key features include persistent state, conditional "
            "routing, and support for human-in-the-loop patterns."
        ),
    ),
    SourceDocument(
        title="Anthropic: Building Effective Agents",
        url="https://www.anthropic.com/engineering/building-effective-agents",
        snippet=(
            "Effective agent systems decompose complex tasks into specialized roles. "
            "A supervisor routes work to worker agents (researcher, analyst, writer). "
            "Guardrails such as max_iterations and timeouts prevent runaway loops. "
            "Tracing every step is essential for debugging and evaluation."
        ),
    ),
    SourceDocument(
        title="OpenAI Agents SDK — Orchestration and Handoffs",
        url="https://platform.openai.com/docs/guides/agents",
        snippet=(
            "The OpenAI Agents SDK supports multi-agent orchestration via handoffs. "
            "Each agent has a defined role and can pass control to another agent. "
            "Tool calls, memory, and guardrails are first-class primitives."
        ),
    ),
    SourceDocument(
        title="Survey: Multi-Agent Systems for Research Automation",
        url="https://arxiv.org/abs/2402.01680",
        snippet=(
            "Recent surveys show multi-agent systems outperform single-agent baselines on "
            "complex research tasks requiring information gathering, synthesis, and writing. "
            "Key metrics: quality score, citation coverage, latency, and cost."
        ),
    ),
    SourceDocument(
        title="GraphRAG: Unlocking LLM Discovery on Narrative Private Data",
        url="https://arxiv.org/abs/2404.16130",
        snippet=(
            "GraphRAG combines knowledge graph construction with retrieval-augmented generation. "
            "It outperforms flat RAG on multi-hop reasoning and relationship queries. "
            "The pipeline: chunk → extract entities/relationships → build graph → query."
        ),
    ),
]


class SearchClient:
    """Provider-agnostic search client.

    Uses Tavily when TAVILY_API_KEY is configured; otherwise returns curated mock results.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._tavily_key = settings.tavily_api_key
        if self._tavily_key:
            logger.info("SearchClient: using Tavily")
        else:
            logger.info("SearchClient: TAVILY_API_KEY not set — using mock sources")

    def search(self, query: str, max_results: int = 5) -> list[SourceDocument]:
        """Return documents relevant to *query*."""

        if self._tavily_key:
            return self._tavily_search(query, max_results)
        return self._mock_search(query, max_results)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _tavily_search(self, query: str, max_results: int) -> list[SourceDocument]:
        try:
            from tavily import TavilyClient  # noqa: PLC0415

            client = TavilyClient(api_key=self._tavily_key)
            response = client.search(query=query, max_results=max_results)
            results = response.get("results", [])
            return [
                SourceDocument(
                    title=r.get("title", ""),
                    url=r.get("url"),
                    snippet=r.get("content", ""),
                )
                for r in results[:max_results]
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily search failed (%s) — falling back to mock", exc)
            return self._mock_search(query, max_results)

    def _mock_search(self, query: str, max_results: int) -> list[SourceDocument]:
        """Return mock sources filtered loosely by query keywords."""

        keywords = {w.lower() for w in query.split() if len(w) > 3}
        scored: list[tuple[int, SourceDocument]] = []
        for doc in _MOCK_SOURCES:
            text = (doc.title + " " + doc.snippet).lower()
            score = sum(1 for kw in keywords if kw in text)
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:max_results]]
