"""Analyst agent — turns research notes into structured insights."""

from __future__ import annotations

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a critical analyst. Given research notes, produce a structured analysis.

Your output must contain exactly these sections:
## Key Claims
List the 3-5 most important claims with supporting evidence.

## Conflicting Viewpoints
Note any disagreements or tensions between sources.

## Evidence Strength
Rate the overall evidence quality: Strong / Moderate / Weak, with a one-sentence justification.

## Recommended Focus
One sentence on what the writer should emphasise in the final answer.
"""


class AnalystAgent(BaseAgent):
    """Turns research notes into structured insights."""

    name = "analyst"

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        """Populate ``state.analysis_notes``."""

        if not state.research_notes:
            msg = "AnalystAgent: research_notes is empty — cannot analyse"
            logger.error(msg)
            state.errors.append(msg)
            raise AgentExecutionError(msg)

        logger.info("AnalystAgent: analysing research notes")
        user_prompt = (
            f"Original query: {state.request.query}\n\nResearch notes:\n{state.research_notes}"
        )

        try:
            response = self._llm.complete(_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:  # noqa: BLE001
            msg = f"AnalystAgent LLM call failed: {exc}"
            logger.error(msg)
            state.errors.append(msg)
            raise AgentExecutionError(msg) from exc

        state.analysis_notes = response.content
        state.add_trace_event(
            "analyst_notes",
            {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
            },
        )
        logger.info("AnalystAgent: analysis written (%d chars)", len(state.analysis_notes))
        return state
