"""HTTP surface.

The audience split is explicit and lives in one place so it can be audited:

* ``public`` -- the Impact Ledger and its verification endpoints. These are
  *intentionally* anonymous. A tamper-evident impact record that only we can
  read is worth nothing; the whole claim is that anyone can check our
  arithmetic. The ledger carries no identifying data by construction (see
  ``ledger.py``).
* ``demo`` -- aggregate and person-level views of the generated district.
  Anonymous while ``DEMO_MODE=true``, because every record is fictional and
  the point of a public demo is that a judge or an NGO can open it without
  an account. The moment the process is configured for real records these
  same routes require an authenticated operator, decided by configuration
  rather than by hope.
* ``operator`` -- anything that would touch real people. Always gated.

Writes in demo mode are rate-limited per client because they consume model
tokens and appointment capacity. The limiter is in-process and therefore
per-replica; it is a spend guard, not a security control, and is documented
as such.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import calibration as cal
from ..agents import escalation as escalation_agent
from ..agents import orchestrator, verifier
from ..agents.base import AgentContext
from ..config import Settings, get_settings
from ..llm import USAGE, FORCE_DETERMINISTIC
from ..models import DebtStatus, EvidenceItem
from ..security import Principal, demo_read, require_admin, require_operator
from ..state import AppState, get_state

router = APIRouter(prefix="/api")

# --- demo spend guard ------------------------------------------------------

_HITS: dict[str, deque[float]] = defaultdict(deque)
AGENT_RUNS_PER_HOUR_PER_CLIENT = 25
BATCH_RUNS_PER_HOUR_PER_CLIENT = 4


def _client_key(request: Request) -> str:
    # Behind a platform proxy the direct peer is the proxy, so prefer the
    # forwarded chain's first hop when present.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request, bucket: str, limit: int) -> None:
    key = f"{bucket}:{_client_key(request)}"
    now = time.monotonic()
    hits = _HITS[key]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Demo limit of {limit} '{bucket}' operations per hour reached "
                "for this client. The limit exists because each run spends "
                "model tokens. Deploy your own instance to lift it."
            ),
        )
    hits.append(now)


def demo_write(
    request: Request, settings: Settings = Depends(get_settings)
) -> Principal | None:
    """Mutating actions on the generated dataset.

    Anonymous in demo mode so the live demo actually works, rate-limited so
    it cannot be used to burn tokens, and a full operator gate as soon as the
    process is configured for real records.
    """
    if not settings.demo_mode:
        return require_operator(request, settings)
    _rate_limit(request, "agent_run", AGENT_RUNS_PER_HOUR_PER_CLIENT)
    return None


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


@router.get("/health", tags=["public"])
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "auth_configured": settings.oidc_configured,
        "llm_enabled": settings.llm_enabled,
        "model": settings.anthropic_model if settings.llm_enabled else None,
        "time": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Aggregate district views
# ---------------------------------------------------------------------------


@router.get("/overview", tags=["demo"])
def overview(
    state: AppState = Depends(get_state), _p=Depends(demo_read)
) -> dict[str, Any]:
    return state.headline()


@router.get("/cascade", tags=["demo"])
def cascade(state: AppState = Depends(get_state), _p=Depends(demo_read)) -> list[dict]:
    return state.cascade()


@router.get("/aging", tags=["demo"])
def aging(state: AppState = Depends(get_state), _p=Depends(demo_read)) -> list[dict]:
    return state.aging()


@router.get("/conditions", tags=["demo"])
def conditions(state: AppState = Depends(get_state), _p=Depends(demo_read)) -> list[dict]:
    return state.by_condition()


@router.get("/panchayats", tags=["demo"])
def panchayats(state: AppState = Depends(get_state), _p=Depends(demo_read)) -> list[dict]:
    return state.by_panchayat()


@router.get("/supply-gaps", tags=["demo"])
def supply_gaps(state: AppState = Depends(get_state), _p=Depends(demo_read)) -> dict:
    return state.supply_gaps()


@router.get("/barriers", tags=["demo"])
def barriers(state: AppState = Depends(get_state), _p=Depends(demo_read)) -> dict:
    return state.barrier_profile()


@router.get("/blocked-reasons", tags=["demo"])
def blocked_reasons(
    state: AppState = Depends(get_state), _p=Depends(demo_read)
) -> list[dict]:
    return state.blocked_reasons()


@router.get("/calibration", tags=["public"])
def calibration_sources() -> dict[str, Any]:
    """Provenance for every constant in the model.

    Deliberately public and deliberately complete, including the constants
    we had to assume. A model whose assumptions you cannot inspect is not
    evidence of anything.
    """
    sources = cal.all_sources()
    return {
        "note": (
            "Every record served by this system in demo mode is fictional. "
            "These published figures set the shape of the simulated district; "
            "they are not an epidemiological estimate for any specific place."
        ),
        "constants": sources,
        "assumed_count": sum(1 for item in sources if item["assumed"] == "yes"),
        "clinical_deadlines_days": cal.CLINICAL_DEADLINE_DAYS,
        "severity_weights_healthy_years": cal.SEVERITY_DALY_WEIGHT,
    }


# ---------------------------------------------------------------------------
# Worklist and individual obligations
# ---------------------------------------------------------------------------


@router.get("/worklist", tags=["demo"])
def worklist(
    limit: int = Query(40, ge=1, le=200),
    panchayat: str | None = None,
    condition: str | None = None,
    state: AppState = Depends(get_state),
    _p=Depends(demo_read),
) -> list[dict[str, Any]]:
    """What the block should work on next, highest expected harm first."""
    debts = orchestrator.worklist(
        state.world,
        state.as_of,
        limit=limit,
        panchayat=panchayat,
        condition=condition,
    )
    out: list[dict[str, Any]] = []
    for debt in debts:
        person = state.world.people[debt.person_id]
        out.append(
            {
                "debt_id": debt.id,
                "condition": debt.condition,
                "label": cal.HUMAN_LABEL.get(debt.condition, debt.condition),
                "required_action": debt.required_action,
                "status": debt.status.value,
                "opened_on": debt.opened_on.isoformat(),
                "deadline_on": debt.deadline_on.isoformat(),
                "days_to_deadline": debt.days_to_deadline(state.as_of),
                "breached": debt.is_breached(state.as_of),
                "severity_weight": cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0),
                "person": {
                    "id": person.id,
                    "display_name": person.display_name,
                    "age": person.age,
                    "sex": person.sex,
                    "village": person.village,
                    "panchayat": person.panchayat,
                    "language": person.language,
                    "literacy": person.literacy,
                    "phone_type": person.phone_type.value,
                    "daily_wage_inr": person.daily_wage_inr,
                    "km_to_district": person.km_to_district,
                    "is_pregnant": person.is_pregnant,
                },
            }
        )
        if len(out) >= limit:
            break
    return out


@router.get("/debts/{debt_id}", tags=["demo"])
def get_debt(
    debt_id: str, state: AppState = Depends(get_state), _p=Depends(demo_read)
) -> dict[str, Any]:
    debt = state.world.debts.get(debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="No such care obligation.")
    person = state.world.people[debt.person_id]
    plan = state.plans.get(debt.plan_id or "")
    event = state.world.events.get(debt.origin_event_id)
    return {
        "debt": debt.model_dump(mode="json"),
        "label": cal.HUMAN_LABEL.get(debt.condition, debt.condition),
        "person": person.model_dump(mode="json"),
        "origin_event": event.model_dump(mode="json") if event else None,
        "plan": plan.model_dump(mode="json") if plan else None,
        "closure_criteria": verifier.closure_criteria(debt),
        "days_to_deadline": debt.days_to_deadline(state.as_of),
        "structural_blocker": escalation_agent.diagnose(
            state.world, debt, state.as_of
        ),
    }


# ---------------------------------------------------------------------------
# The agent pipeline
# ---------------------------------------------------------------------------


@router.post("/debts/{debt_id}/plan", tags=["agents"])
async def plan_debt(
    debt_id: str,
    state: AppState = Depends(get_state),
    _p=Depends(demo_write),
) -> dict[str, Any]:
    debt = state.world.debts.get(debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="No such care obligation.")
    ctx = AgentContext(world=state.world, ledger=state.ledger, as_of=state.as_of)
    run = await orchestrator.plan_one(ctx, debt)
    if run.plan is not None:
        state.register_plan(run.plan)
    state.persist_debt(debt)
    return {
        "run": run.model_dump(mode="json"),
        "shared": {
            "binding_constraint": ctx.shared.get("binding_constraint"),
            "narrative": ctx.shared.get("reality_narrative"),
            "shortlist": ctx.shared.get("shortlist"),
            "safety_overrides": ctx.shared.get("safety_overrides", []),
            "no_viable_plan": bool(ctx.shared.get("no_viable_plan")),
        },
        "llm_usage": USAGE.as_dict(),
    }


@router.get("/debts/{debt_id}/plan/stream", tags=["agents"])
async def plan_debt_stream(
    debt_id: str,
    request: Request,
    state: AppState = Depends(get_state),
    _p=Depends(demo_write),
) -> StreamingResponse:
    """Server-sent events, one frame per agent, so the work is visible.

    Consumed with ``fetch`` and a stream reader rather than ``EventSource``,
    because EventSource cannot carry an Authorization header and this route
    is gated whenever the process holds real records.
    """
    debt = state.world.debts.get(debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="No such care obligation.")

    async def frames():
        ctx = AgentContext(world=state.world, ledger=state.ledger, as_of=state.as_of)
        try:
            async for event in orchestrator.plan_one_streaming(ctx, debt):
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
            if ctx.shared.get("plan") is not None:
                state.register_plan(ctx.shared["plan"])
            state.persist_debt(debt)
            tail = {
                "type": "closed",
                "llm_usage": USAGE.as_dict(),
                "safety_overrides": ctx.shared.get("safety_overrides", []),
            }
            yield f"data: {json.dumps(tail, default=str)}\n\n"
        except asyncio.CancelledError:  # client navigated away
            raise

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


class BatchRequest(BaseModel):
    limit: int = Field(100, ge=1, le=1000)
    panchayat: str | None = None
    # Bulk runs never spend tokens. The deterministic core is the production
    # path for volume work anyway -- a block of 200,000 people cannot have a
    # model call per follow-up, and the design does not require one.
    use_llm: Literal[False] = False


@router.post("/simulate/batch", tags=["agents"])
async def simulate_batch(
    request: Request,
    body: BatchRequest = Body(default_factory=BatchRequest),
    state: AppState = Depends(get_state),
    _p=Depends(demo_write),
) -> dict[str, Any]:
    """Plan a slice of the backlog at once, to show the burn-down.

    This is the honest demonstration of scale: thousands of obligations
    planned by the deterministic optimiser in seconds, with the model
    reserved for the cases a human will actually read.
    """
    settings = get_settings()
    if settings.demo_mode:
        _rate_limit(request, "batch", BATCH_RUNS_PER_HOUR_PER_CLIENT)

    token = FORCE_DETERMINISTIC.set(True)
    started = time.perf_counter()
    try:
        debts = orchestrator.worklist(state.world, state.as_of, limit=body.limit * 3)
        if body.panchayat:
            debts = [
                debt
                for debt in debts
                if state.world.people[debt.person_id].panchayat == body.panchayat
            ]
        debts = debts[: body.limit]
        runs = await orchestrator.plan_batch(
            state.world, state.ledger, state.as_of, debts
        )
    finally:
        FORCE_DETERMINISTIC.reset(token)

    planned = [run for run in runs if run.plan is not None]
    for run in planned:
        assert run.plan is not None
        state.register_plan(run.plan)
    for debt in debts:
        state.persist_debt(debt)

    savings = sum(
        float(run.plan.counterfactual.get("savings_inr") or 0.0)
        for run in planned
        if run.plan
    )
    km = sum(
        float(run.plan.counterfactual.get("travel_km_avoided") or 0.0)
        for run in planned
        if run.plan
    )
    noshow_delta = sum(
        float(run.plan.counterfactual.get("no_show_reduction_pp") or 0.0) / 100.0
        for run in planned
        if run.plan
    )
    zero_travel = sum(
        1 for run in planned if run.plan and run.plan.cost.travel_km <= 2.0
    )
    return {
        "attempted": len(debts),
        "planned": len(planned),
        "unplannable": len(debts) - len(planned),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "patient_rupees_saved": round(savings, 0),
        "patient_travel_km_avoided": round(km, 0),
        "expected_additional_attendances": round(noshow_delta, 1),
        "plans_requiring_no_travel": zero_travel,
        "note": (
            "Planned with the deterministic optimiser only, no model calls. "
            "Expected additional attendances is the summed reduction in "
            "predicted no-show probability against the conventional referral "
            "each patient would otherwise have received."
        ),
    }


# ---------------------------------------------------------------------------
# Closure -- the only way a care debt ends
# ---------------------------------------------------------------------------


class ClosureRequest(BaseModel):
    kind: Literal[
        "bp_recorded",
        "glucose_recorded",
        "drug_dispensed",
        "test_result_received",
        "treatment_initiated",
        "specialist_note",
        "visit_logged",
        "immunisation_recorded",
    ]
    detail: str = Field(min_length=1, max_length=400)
    recorded_by: str = Field(min_length=1, max_length=120)
    facility_id: str | None = None
    corroborated: bool = True


@router.post("/debts/{debt_id}/close", tags=["agents"])
async def close_debt(
    debt_id: str,
    body: ClosureRequest,
    state: AppState = Depends(get_state),
    _p=Depends(demo_write),
) -> dict[str, Any]:
    """Close an obligation with evidence. There is no other way to close one.

    Note the absence of a 'mark as done' field anywhere in this request
    body. That absence is the feature.
    """
    debt = state.world.debts.get(debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="No such care obligation.")
    if debt.status == DebtStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Already closed.")

    evidence = EvidenceItem(
        kind=body.kind,
        recorded_at=datetime.now(timezone.utc),
        recorded_by=body.recorded_by,
        detail=body.detail,
        facility_id=body.facility_id,
        corroborated=body.corroborated,
    )
    ctx = AgentContext(world=state.world, ledger=state.ledger, as_of=state.as_of)
    if debt.plan_id and debt.plan_id in state.plans:
        ctx.shared["plan"] = state.plans[debt.plan_id]

    decision = verifier.close_with_evidence(ctx, debt, evidence)
    audit = await verifier.audit(debt, evidence)
    if decision["accepted"]:
        state.persist_debt(debt)
    else:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Evidence does not discharge this obligation.",
                "decision": decision,
            },
        )
    return {"decision": decision, "plausibility_audit": audit}


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------


@router.get("/escalations", tags=["demo"])
def list_escalations(
    state: AppState = Depends(get_state), _p=Depends(demo_read)
) -> list[dict]:
    return [
        esc.model_dump(mode="json")
        for esc in sorted(
            state.escalations.values(), key=lambda item: item.raised_on, reverse=True
        )
    ]


@router.get("/escalations/clusters", tags=["demo"])
def escalation_clusters(
    limit: int = Query(8, ge=1, le=30),
    state: AppState = Depends(get_state),
    _p=Depends(demo_read),
) -> list[dict]:
    """Unclosable obligations grouped by the system failure causing them."""
    debts = state.world.open_debts()
    return escalation_agent.cluster(state.world, debts, state.as_of)[:limit]


@router.post("/escalations/run", tags=["agents"])
async def run_escalations(
    top: int = Query(3, ge=1, le=6),
    state: AppState = Depends(get_state),
    _p=Depends(demo_write),
) -> dict[str, Any]:
    clusters = escalation_agent.cluster(
        state.world, state.world.open_debts(), state.as_of
    )[:top]
    written = []
    for group in clusters:
        esc = await escalation_agent.write_brief(group, state.as_of)
        state.persist_escalation(esc)
        for debt_id in group["debt_ids"]:
            debt = state.world.debts.get(debt_id)
            if debt and debt.status != DebtStatus.CLOSED:
                debt.escalation_id = esc.id
        state.ledger.append(
            "debt_escalated",
            person_id="__cluster__",
            debt_id=esc.id,
            payload={
                "escalated_to_role": esc.to_role,
                "systemic_cause": esc.systemic_cause,
                "panchayat_code": group["panchayat"],
                "reason": group["cause"],
            },
        )
        written.append(esc.model_dump(mode="json"))
    return {"escalations": written, "clusters_considered": len(clusters)}


# ---------------------------------------------------------------------------
# Impact ledger -- intentionally public
# ---------------------------------------------------------------------------


@router.get("/ledger/summary", tags=["public"])
def ledger_summary(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return state.ledger.impact()


@router.get("/ledger/entries", tags=["public"])
def ledger_entries(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    return {
        "total": state.ledger.count(),
        "offset": offset,
        "entries": state.ledger.entries(offset=offset, limit=limit),
        "privacy_note": (
            "Entries carry no names, phone numbers, villages or identifiers. "
            "Each subject is a keyed hash of an internal record id, which "
            "permits counting distinct people without revealing who they are."
        ),
    }


@router.get("/ledger/verify", tags=["public"])
def ledger_verify(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return state.ledger.verify()


@router.get("/ledger/public-key", tags=["public"])
def ledger_public_key(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {
        "algorithm": "Ed25519",
        "key_id": state.ledger.key_id,
        "public_key_b64": state.ledger.public_key_b64(),
        "usage": (
            "Verify each entry's signature over the bytes of its entry_hash. "
            "See /api/ledger/verify for the canonicalisation rules."
        ),
    }


# ---------------------------------------------------------------------------
# Operator-only
# ---------------------------------------------------------------------------


@router.get("/operator/whoami", tags=["operator"])
def whoami(principal: Principal = Depends(require_operator)) -> dict[str, Any]:
    return {
        "subject": principal.subject,
        "roles": sorted(principal.roles),
        "issuer": principal.issuer,
        "verified_via": principal.via,
    }


@router.post("/operator/reset-demo", tags=["operator"])
def reset_demo(
    principal: Principal = Depends(require_admin),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    """Rebuild the generated district. Admin only, and never touches the ledger.

    The ledger is append-only on purpose: being able to reset the demo world
    while the signed impact record survives is exactly the property that
    makes the record worth anything.
    """
    state.db.run("DELETE FROM debt_state")
    from ..data.generator import build_world

    state.world = build_world(seed=state.settings.seed)
    state.as_of = state.world.as_of
    state.plans.clear()
    return {
        "reset": True,
        "by": principal.subject,
        "ledger_entries_preserved": state.ledger.count(),
    }


@router.get("/llm/usage", tags=["public"])
def llm_usage(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "enabled": settings.llm_enabled,
        "model": settings.anthropic_model if settings.llm_enabled else None,
        "budget_calls_per_hour": settings.llm_max_calls_per_hour,
        **USAGE.as_dict(),
        "note": (
            "Deterministic fallbacks are not failures. Bulk planning never "
            "calls the model by design, and the pipeline is built to produce "
            "a complete, safe plan with no model available at all."
        ),
    }
