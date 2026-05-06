"""LangGraph multi-agent workflow.

Graph topology:
  START → supervisor → {researcher | analyst | writer | END}
  Each worker node returns to supervisor after completing its task.
  Supervisor routes to END when final_answer is populated or max_iterations reached.
"""

from __future__ import annotations

import logging
from typing import Any

from multi_agent_research_lab.agents.analyst import AnalystAgent
from multi_agent_research_lab.agents.researcher import ResearcherAgent
from multi_agent_research_lab.agents.supervisor import SupervisorAgent
from multi_agent_research_lab.agents.writer import WriterAgent
from multi_agent_research_lab.core.state import ResearchState

logger = logging.getLogger(__name__)


def _state_to_dict(state: ResearchState) -> dict[str, Any]:
    return state.model_dump()


def _dict_to_state(data: dict[str, Any]) -> ResearchState:
    return ResearchState.model_validate(data)


class MultiAgentWorkflow:
    """Builds and runs the multi-agent graph using LangGraph."""

    def __init__(self) -> None:
        self._supervisor = SupervisorAgent()
        self._researcher = ResearcherAgent()
        self._analyst = AnalystAgent()
        self._writer = WriterAgent()

    # ------------------------------------------------------------------
    # Node functions — LangGraph nodes receive/return plain dicts
    # ------------------------------------------------------------------

    def _supervisor_node(self, data: dict[str, Any]) -> dict[str, Any]:
        state = _dict_to_state(data)
        state = self._supervisor.run(state)
        return _state_to_dict(state)

    def _researcher_node(self, data: dict[str, Any]) -> dict[str, Any]:
        state = _dict_to_state(data)
        state = self._researcher.run(state)
        return _state_to_dict(state)

    def _analyst_node(self, data: dict[str, Any]) -> dict[str, Any]:
        state = _dict_to_state(data)
        state = self._analyst.run(state)
        return _state_to_dict(state)

    def _writer_node(self, data: dict[str, Any]) -> dict[str, Any]:
        state = _dict_to_state(data)
        state = self._writer.run(state)
        return _state_to_dict(state)

    # ------------------------------------------------------------------
    # Conditional edge — read last route from route_history
    # ------------------------------------------------------------------

    @staticmethod
    def _route(data: dict[str, Any]) -> str:
        route_history: list[str] = data.get("route_history", [])
        if not route_history:
            return "researcher"
        last = route_history[-1]
        if last == "done":
            return "__end__"
        return last  # researcher | analyst | writer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> Any:
        """Create and return a compiled LangGraph graph."""

        from langgraph.graph import END, StateGraph  # noqa: PLC0415

        # LangGraph requires a TypedDict or Annotated schema; we use plain dict
        # and annotate with Any so it accepts our serialised ResearchState.
        graph = StateGraph(dict)

        graph.add_node("supervisor", self._supervisor_node)
        graph.add_node("researcher", self._researcher_node)
        graph.add_node("analyst", self._analyst_node)
        graph.add_node("writer", self._writer_node)

        # Entry point
        graph.set_entry_point("supervisor")

        # After supervisor, route conditionally
        graph.add_conditional_edges(
            "supervisor",
            self._route,
            {
                "researcher": "researcher",
                "analyst": "analyst",
                "writer": "writer",
                "__end__": END,
            },
        )

        # Each worker returns to supervisor
        graph.add_edge("researcher", "supervisor")
        graph.add_edge("analyst", "supervisor")
        graph.add_edge("writer", "supervisor")

        return graph.compile()

    def run(self, state: ResearchState) -> ResearchState:
        """Execute the compiled graph and return the final ResearchState."""

        compiled = self.build()
        initial = _state_to_dict(state)
        logger.info("MultiAgentWorkflow: starting graph execution")
        result = compiled.invoke(initial)
        logger.info("MultiAgentWorkflow: graph execution complete")
        return _dict_to_state(result)
