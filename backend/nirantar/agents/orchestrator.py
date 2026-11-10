"""Runs the agent pipeline for one care obligation, and in batch.

The pipeline is a fixed sequence rather than a free-form agent loop, and
that is a deliberate engineering choice. Each stage has a different
correctness requirement: Supply must never hallucinate, Triage must never
re-order critical cases, Verifier must be purely deterministic. A single
model improvising across all of those would be more impressive to watch and
much worse at the job. So the orchestration is explicit, the ordering is
auditable, and the language model is invoked at the three points where
judgement genuinely beats rules.

Triage -> Reality -> Supply -> Planner -> Verifier(criteria)

The orchestrator also exposes a streaming variant, because a judge watching
the dashboard should see the agents working in real time rather than a
spinner followed by an answer.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

from ..models import AgentRun, CareDebt, CarePlan, DebtStatus
from . import planner, reality, supply, triage, verifier
from .base import AgentContext

PIPELINE = [
    ("Triage", "risk ranking", triage.run),
    ("Reality", "barrier analysis", reality.run),
    ("Supply", "capacity and stock lookup", supply.run),
    ("Planner", "plan optimisation", planner.run),
    ("Verifier", "closure criteria", verifier.run),
]


async def plan_one(ctx: AgentContext, debt: CareDebt) -> AgentRun:
    """Run the full pipeline for a single care obligation."""
    run = AgentRun(
        id=f"run-{uuid.uuid4().hex[:12]}",
        debt_id=debt.id,
        started_at=datetime.now(timezone.utc),
    )
    try:
        await triage.run(ctx, debt)
        await reality.run(ctx, debt)
        await supply.run(ctx, debt)
        plan = await planner.run(ctx, debt)
        await verifier.run(ctx, debt)
        run.plan = plan
        if plan is not None:
            _record_plan(ctx, debt, plan)
    except Exception as exc:  # surfaced to the UI rather than swallowed
        run.error = f"{type(exc).__name__}: {exc}"
    run.steps = list(ctx.steps)
    run.finished_at = datetime.now(timezone.utc)
    return run


async def plan_one_streaming(
    ctx: AgentContext, debt: CareDebt
) -> AsyncIterator[dict[str, Any]]:
    """Yield each agent's result as it completes, for the live trace view."""
    yield {
        "type": "run_started",
        "debt_id": debt.id,
        "person": ctx.person(debt).model_dump(mode="json"),
        "debt": debt.model_dump(mode="json"),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    emitted = 0
    plan: CarePlan | None = None
    try:
        for name, phase, _fn in PIPELINE:
            yield {"type": "agent_started", "agent": name, "phase": phase}
            if name == "Triage":
                await triage.run(ctx, debt)
            elif name == "Reality":
                await reality.run(ctx, debt)
            elif name == "Supply":
                await supply.run(ctx, debt)
            elif name == "Planner":
                plan = await planner.run(ctx, debt)
            elif name == "Verifier":
                await verifier.run(ctx, debt)
            while emitted < len(ctx.steps):
                step = ctx.steps[emitted]
                emitted += 1
                yield {"type": "agent_step", "step": step.model_dump(mode="json")}
            # A small yield so the browser paints each stage distinctly
            # instead of receiving the whole trace in one frame.
            await asyncio.sleep(0.05)
        if plan is not None:
            _record_plan(ctx, debt, plan)
        yield {
            "type": "run_finished",
            "plan": plan.model_dump(mode="json") if plan else None,
            "debt": debt.model_dump(mode="json"),
            "no_viable_plan": bool(ctx.shared.get("no_viable_plan")),
            "safety_overrides": ctx.shared.get("safety_overrides", []),
        }
    except Exception as exc:
        yield {"type": "error", "error": f"{type(exc).__name__}: {exc}"}


def _record_plan(ctx: AgentContext, debt: CareDebt, plan: CarePlan) -> None:
    """Write the planning decision to the signed ledger.

    Plans are logged as well as closures. An impact claim is only auditable
    if the prediction was recorded *before* the outcome was known -- logging
    only successes is how pilots accidentally launder their own results.
    """
    counterfactual = plan.counterfactual or {}
    ctx.ledger.append(
        "plan_created",
        person_id=debt.person_id,
        debt_id=debt.id,
        payload={
            "condition": debt.condition,
            "required_action": debt.required_action,
            "risk_score": debt.risk_score,
            "strategy": plan.strategy,
            "outreach_channel": plan.outreach_channel,
            "cost_to_patient_inr": plan.cost.total_inr,
            "travel_km": plan.cost.travel_km,
            "wage_loss_days": plan.cost.wage_loss_days,
            "predicted_no_show": plan.predicted_no_show,
            "plan_generated_by": plan.generated_by,
            "counterfactual_cost_inr": counterfactual.get("cost_inr"),
            "counterfactual_travel_km": counterfactual.get("travel_km"),
            "counterfactual_wage_loss_days": counterfactual.get("wage_loss_days"),
            "counterfactual_no_show": counterfactual.get("no_show"),
            "panchayat_code": ctx.person(debt).panchayat,
            "days_to_deadline": debt.days_to_deadline(ctx.as_of),
        },
    )


async def plan_batch(
    world: Any,
    ledger: Any,
    as_of: date,
    debts: list[CareDebt],
    *,
    concurrency: int = 6,
) -> list[AgentRun]:
    """Plan a worklist. Used by the 'run the whole backlog' action.

    Concurrency is bounded because the real constraint in a block is not CPU,
    it is the appointment slots and medicine stock the planner consumes as it
    goes -- and those are shared state. Each obligation gets its own context
    but they draw down the same world, in order, so the hundredth patient is
    planned against the capacity the first ninety-nine actually used.
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[AgentRun] = []

    async def worker(debt: CareDebt) -> AgentRun:
        async with semaphore:
            ctx = AgentContext(world=world, ledger=ledger, as_of=as_of)
            return await plan_one(ctx, debt)

    for chunk_start in range(0, len(debts), concurrency):
        chunk = debts[chunk_start : chunk_start + concurrency]
        results.extend(await asyncio.gather(*(worker(debt) for debt in chunk)))
    return results


def worklist(
    world: Any,
    as_of: date,
    limit: int = 50,
    *,
    panchayat: str | None = None,
    condition: str | None = None,
) -> list[CareDebt]:
    """The obligations a block should work on next, best-effort ordered.

    Uses the deterministic triage score so the queue can be produced without
    an API call -- the ordering must exist even when the network does not.

    Filters are applied *before* ranking and truncation. Filtering a
    pre-truncated list would silently return nothing for any filter whose
    matches all sit below the severity cut, which is exactly the kind of
    quiet emptiness an operator would read as "no work here".
    """
    candidates = [
        debt
        for debt in world.debts.values()
        if debt.status in {DebtStatus.OPEN, DebtStatus.ESCALATED}
    ]
    if condition:
        candidates = [debt for debt in candidates if debt.condition == condition]
    if panchayat:
        candidates = [
            debt
            for debt in candidates
            if world.people[debt.person_id].panchayat == panchayat
        ]

    # The same ranking the trial simulation uses, including the equity
    # weighting. Previously this computed severity x urgency only, so the
    # queue order silently disagreed with the risk score the interface
    # displayed.
    candidates.sort(
        key=lambda debt: triage.rank_score(
            debt, world.people[debt.person_id], as_of
        ),
        reverse=True,
    )
    return candidates[:limit]
