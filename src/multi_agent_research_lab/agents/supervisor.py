"""Supervisor / router agent.

Routing policy:
  iteration 0 → researcher   (always gather sources first)
  iteration 1 → analyst      (analyse what was found)
  iteration 2 → writer       (produce final answer)
  iteration ≥ 3 → done       (stop; also stop if max_iterations reached)

If a previous agent recorded an error the supervisor routes to "done" immediately
so the workflow does not loop forever.
"""

from __future__ import annotations

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.state import ResearchState

logger = logging.getLogger(__name__)

_ROUTE_SEQUENCE = ["researcher", "analyst", "writer"]


class SupervisorAgent(BaseAgent):
    """Decides which worker should run next and when to stop."""

    name = "supervisor"

    def run(self, state: ResearchState) -> ResearchState:
        """Update ``state.route_history`` with the next route and return state."""

        settings = get_settings()

        # Hard stop: too many iterations or errors accumulated
        if state.iteration >= settings.max_iterations:
            logger.warning(
                "Supervisor: max_iterations=%d reached — stopping",
                settings.max_iterations,
            )
            state.record_route("done")
            return state

        if state.errors:
            logger.warning("Supervisor: errors detected — stopping early: %s", state.errors)
            state.record_route("done")
            return state

        # Determine next step based on what is already populated
        if state.research_notes is None:
            next_route = "researcher"
        elif state.analysis_notes is None:
            next_route = "analyst"
        elif state.final_answer is None:
            next_route = "writer"
        else:
            next_route = "done"

        logger.info("Supervisor: iteration=%d → %s", state.iteration, next_route)
        state.record_route(next_route)
        state.add_trace_event(
            "supervisor_route",
            {"next": next_route, "iteration": state.iteration},
        )
        return state
