"""Researcher agent — gathers sources and writes concise research notes."""

from __future__ import annotations

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient
from multi_agent_research_lab.services.search_client import SearchClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a research assistant. Given a user query and a set of source documents,
write concise, factual research notes (300-500 words).

Rules:
- Cite sources by title when making a claim.
- Do not invent facts not present in the sources.
- Use bullet points for key findings.
- End with a "Gaps" section listing what is still unknown.
"""


class ResearcherAgent(BaseAgent):
    """Collects sources and creates concise research notes."""

    name = "researcher"

    def __init__(
        self,
        llm: LLMClient | None = None,
        search: SearchClient | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._search = search or SearchClient()

    def run(self, state: ResearchState) -> ResearchState:
        """Populate ``state.sources`` and ``state.research_notes``."""

        query = state.request.query
        logger.info("ResearcherAgent: searching for '%s'", query)

        try:
            sources = self._search.search(query, max_results=state.request.max_sources)
        except Exception as exc:  # noqa: BLE001
            msg = f"ResearcherAgent search failed: {exc}"
            logger.error(msg)
            state.errors.append(msg)
            raise AgentExecutionError(msg) from exc

        state.sources = sources
        state.add_trace_event("researcher_search", {"num_sources": len(sources)})

        # Build context block from sources
        source_block = "\n\n".join(
            f"[{i + 1}] {doc.title}\n{doc.snippet}" for i, doc in enumerate(sources)
        )

        user_prompt = f"Query: {query}\n\nSources:\n{source_block}"

        try:
            response = self._llm.complete(_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:  # noqa: BLE001
            msg = f"ResearcherAgent LLM call failed: {exc}"
            logger.error(msg)
            state.errors.append(msg)
            raise AgentExecutionError(msg) from exc

        state.research_notes = response.content
        state.add_trace_event(
            "researcher_notes",
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
            },
        )
        logger.info("ResearcherAgent: notes written (%d chars)", len(state.research_notes))
        return state
