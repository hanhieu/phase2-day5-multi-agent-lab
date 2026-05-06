"""Tests for the implemented supervisor agent (replaces the original TODO stub test)."""

from multi_agent_research_lab.agents import SupervisorAgent
from multi_agent_research_lab.core.schemas import ResearchQuery
from multi_agent_research_lab.core.state import ResearchState


def test_supervisor_routes_to_researcher_first() -> None:
    """Supervisor should route to researcher when no notes exist yet."""

    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    result = SupervisorAgent().run(state)
    assert result.route_history[-1] == "researcher"


def test_supervisor_routes_to_analyst_after_research() -> None:
    """Supervisor should route to analyst once research_notes is populated."""

    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    state.research_notes = "Some research notes"
    result = SupervisorAgent().run(state)
    assert result.route_history[-1] == "analyst"


def test_supervisor_routes_to_writer_after_analysis() -> None:
    """Supervisor should route to writer once both notes are populated."""

    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    state.research_notes = "Some research notes"
    state.analysis_notes = "Some analysis"
    result = SupervisorAgent().run(state)
    assert result.route_history[-1] == "writer"


def test_supervisor_routes_done_when_complete() -> None:
    """Supervisor should route to done when final_answer is present."""

    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    state.research_notes = "notes"
    state.analysis_notes = "analysis"
    state.final_answer = "The answer."
    result = SupervisorAgent().run(state)
    assert result.route_history[-1] == "done"


def test_supervisor_stops_on_errors() -> None:
    """Supervisor should route to done immediately when errors are present."""

    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    state.errors.append("something went wrong")
    result = SupervisorAgent().run(state)
    assert result.route_history[-1] == "done"
