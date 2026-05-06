"""Writer agent — produces the final answer from research and analysis notes."""

from __future__ import annotations

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a technical writer producing a final research answer for {audience}.

Guidelines:
- Write 400-600 words.
- Start with a one-paragraph executive summary.
- Use the research notes and analyst insights to support every claim.
- Cite sources inline as [Source Title].
- End with a "References" section listing all cited sources with URLs if available.
- Be clear, precise, and avoid filler phrases.
"""


class WriterAgent(BaseAgent):
    """Produces final answer from research and analysis notes."""

    name = "writer"

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        """Populate ``state.final_answer``."""

        if not state.research_notes:
            msg = "WriterAgent: research_notes is empty"
            logger.error(msg)
            state.errors.append(msg)
            raise AgentExecutionError(msg)

        logger.info("WriterAgent: composing final answer")

        system_prompt = _SYSTEM_PROMPT.format(audience=state.request.audience)

        source_refs = "\n".join(f"- {doc.title}: {doc.url or 'no URL'}" for doc in state.sources)

        user_prompt = (
            f"Query: {state.request.query}\n\n"
            f"Research notes:\n{state.research_notes}\n\n"
            f"Analysis:\n{state.analysis_notes or '(no analysis provided)'}\n\n"
            f"Available sources:\n{source_refs}"
        )

        try:
            response = self._llm.complete(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            msg = f"WriterAgent LLM call failed: {exc}"
            logger.error(msg)
            state.errors.append(msg)
            raise AgentExecutionError(msg) from exc

        state.final_answer = response.content
        state.add_trace_event(
            "writer_answer",
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
            },
        )
        logger.info("WriterAgent: final answer written (%d chars)", len(state.final_answer))
        return state
