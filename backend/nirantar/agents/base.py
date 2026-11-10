"""Shared plumbing for the agent pipeline."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterator

from ..data.generator import World
from ..ledger import ImpactLedger
from ..models import AgentStep, CareDebt, Person


@dataclass
class AgentContext:
    """Everything the agents are allowed to touch.

    Passing one explicit context rather than reaching for globals keeps the
    agents unit-testable and makes the blast radius of each agent obvious.
    """

    world: World
    ledger: ImpactLedger
    as_of: date
    steps: list[AgentStep] = field(default_factory=list)
    # Scratchpad the agents hand forward to each other.
    shared: dict[str, Any] = field(default_factory=dict)

    def person(self, debt: CareDebt) -> Person:
        return self.world.people[debt.person_id]


@contextmanager
def timed(
    ctx: AgentContext, agent: str, phase: str
) -> Iterator[dict[str, Any]]:
    """Record an agent step with real wall-clock timing.

    The dashboard shows these durations. They are measured, not decorative:
    if the pipeline is slow, the demo shows it being slow.
    """
    started = datetime.now(timezone.utc)
    clock = time.perf_counter()
    sink: dict[str, Any] = {"summary": "", "detail": {}, "used_llm": False, "tokens": None}
    try:
        yield sink
    finally:
        ctx.steps.append(
            AgentStep(
                agent=agent,
                phase=phase,
                started_at=started,
                duration_ms=int((time.perf_counter() - clock) * 1000),
                summary=str(sink.get("summary") or ""),
                detail=dict(sink.get("detail") or {}),
                used_llm=bool(sink.get("used_llm")),
                tokens=sink.get("tokens"),
            )
        )
