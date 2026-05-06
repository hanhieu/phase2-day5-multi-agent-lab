"""Tracing hooks.

Provides two layers:
1. trace_span() — a lightweight context manager that records duration and
   attributes into a plain dict (always available, zero dependencies).
2. export_trace_json() — writes the full state.trace list to a JSON file
   so every run has a machine-readable trace artefact in reports/.

To plug in LangSmith or Langfuse, replace the body of trace_span() with
the provider's span context manager and keep the same yield contract.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Minimal span context manager.

    Usage::

        with trace_span("researcher", {"query": q}) as span:
            ...  # do work
        print(span["duration_seconds"])

    To switch to LangSmith, replace this body with:
        with langsmith.trace(name, inputs=attributes) as run:
            yield {"name": name, "attributes": attributes or {}, "run": run}
    """

    started = perf_counter()
    span: dict[str, Any] = {
        "name": name,
        "attributes": attributes or {},
        "duration_seconds": None,
    }
    try:
        yield span
    finally:
        span["duration_seconds"] = perf_counter() - started
        logger.debug(
            "trace_span '%s' finished in %.3fs",
            name,
            span["duration_seconds"],
        )


def export_trace_json(
    trace: list[dict[str, Any]],
    path: Path,
) -> None:
    """Write a trace list to *path* as pretty-printed JSON.

    Called automatically by the CLI after every run so each
    reports/<run>/<ts>/ folder contains a trace.json file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    logger.debug("Trace exported to %s (%d events)", path, len(trace))
