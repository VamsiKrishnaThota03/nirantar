"""Verifier agent: nothing is closed without evidence.

Every reporting system in global health drifts towards the same failure. A
target exists, the target is measured by a status field, and the status field
is set by the person being measured. Within two quarters the field says 94%
and nobody believes it.

Nirantar closes that loop by making closure a derived fact rather than a
declaration. A care debt is discharged only when a specific artefact exists:
a blood pressure *value*, a dispensing record, a test result, a treatment
start date. "Patient counselled", "follow-up done", "referred" -- none of
these close anything. There is deliberately no API through which a care debt
can be marked closed without an evidence payload, and the ledger records
whether the evidence was corroborated by a facility record or merely asserted
by a human.

This is also why the impact numbers in this project can be trusted: they are
a count of artefacts, not a count of claims.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import calibration as cal
from ..llm import bounded_text, complete_json
from ..models import CareDebt, DebtStatus, EvidenceItem
from .base import AgentContext, timed

AGENT = "Verifier"

# What counts as proof that each kind of obligation was actually discharged.
REQUIRED_EVIDENCE: dict[str, set[str]] = {
    "confirm_diagnosis": {"bp_recorded", "glucose_recorded", "test_result_received"},
    "refill_medication": {"drug_dispensed"},
    "followup_test": {"test_result_received"},
    "initiate_treatment": {"treatment_initiated"},
    "specialist_review": {"specialist_note"},
    "routine_visit": {"visit_logged", "immunisation_recorded", "bp_recorded"},
}

HUMAN_EVIDENCE_LABEL = {
    "bp_recorded": "a blood-pressure value recorded against this patient",
    "glucose_recorded": "a blood-glucose value recorded against this patient",
    "drug_dispensed": "a dispensing record for the prescribed medicine",
    "test_result_received": "a laboratory or point-of-care test result",
    "treatment_initiated": "a treatment start record",
    "specialist_note": "a specialist's examination note",
    "visit_logged": "a logged clinical encounter",
    "immunisation_recorded": "an immunisation entry against the child's record",
}

SYSTEM = """You are the verification component of Nirantar, a care-continuity \
system for Indian primary health care. A care obligation has been submitted \
for closure with an evidence payload. A deterministic rule has already decided \
whether the evidence type satisfies the requirement -- that decision is final \
and you cannot change it.

Your job is to read the evidence detail and flag anything that looks \
implausible or inconsistent to an experienced auditor: a blood pressure value \
that is physiologically improbable, a dispensing quantity that does not match \
a month's course, a timestamp before the obligation was even created, a \
pattern suggesting bulk data entry rather than real clinical contact.

Reply with JSON only:
{"plausible": true | false,
 "note": "<= 240 characters>",
 "audit_flags": ["<short phrase>", ...]}

Setting plausible to false does not block a closure that the rules accepted; \
it marks the entry for human audit. Say so plainly when something looks wrong."""


def required_evidence_for(action: str) -> set[str]:
    return REQUIRED_EVIDENCE.get(action, {"visit_logged"})


def closure_criteria(debt: CareDebt) -> dict[str, Any]:
    kinds = sorted(required_evidence_for(debt.required_action))
    return {
        "action": debt.required_action,
        "accepts_any_of": kinds,
        "in_plain_words": [HUMAN_EVIDENCE_LABEL.get(kind, kind) for kind in kinds],
        "will_not_accept": [
            "patient counselled",
            "patient referred",
            "follow-up advised",
            "message delivered",
            "call answered",
        ],
        "note": (
            "Outreach is an input, not an outcome. None of the rejected "
            "entries above can close this obligation."
        ),
    }


def adjudicate(debt: CareDebt, evidence: EvidenceItem) -> dict[str, Any]:
    """Pure, deterministic decision. The only thing that can close a debt."""
    accepted_kinds = required_evidence_for(debt.required_action)
    satisfies = evidence.kind in accepted_kinds
    problems: list[str] = []
    if not satisfies:
        problems.append(
            f"evidence of type '{evidence.kind}' does not discharge a "
            f"'{debt.required_action}' obligation; "
            f"accepts: {sorted(accepted_kinds)}"
        )
    recorded_on = evidence.recorded_at.date()
    if recorded_on < debt.opened_on:
        problems.append(
            "evidence predates the care obligation it claims to discharge"
        )
    return {
        "accepted": satisfies and not problems,
        "satisfies_requirement": satisfies,
        "problems": problems,
        "corroborated": evidence.corroborated,
        "criteria": closure_criteria(debt),
    }


async def audit(debt: CareDebt, evidence: EvidenceItem) -> dict[str, Any]:
    """Optional plausibility review. Advisory; never gates a valid closure."""
    prompt = (
        f"Care obligation: {debt.condition} / {debt.required_action}\n"
        f"Opened: {debt.opened_on.isoformat()}\n"
        f"Clinical deadline: {debt.deadline_on.isoformat()}\n"
        f"Evidence type: {evidence.kind}\n"
        f"Evidence detail: {evidence.detail}\n"
        f"Recorded at: {evidence.recorded_at.isoformat()}\n"
        f"Recorded by: {evidence.recorded_by}\n"
        f"Corroborated by a facility record: {evidence.corroborated}\n"
    )
    response = await complete_json(system=SYSTEM, prompt=prompt, max_tokens=400)
    if response is None:
        return {
            "reviewed": False,
            "plausible": None,
            "note": "Plausibility review unavailable; deterministic rules applied.",
            "audit_flags": [],
        }
    flags = response.get("audit_flags")
    return {
        "reviewed": True,
        "plausible": bool(response.get("plausible", True)),
        "note": bounded_text(response.get("note"), max_chars=240, default=""),
        "audit_flags": [str(item)[:60] for item in flags[:5]]
        if isinstance(flags, list)
        else [],
    }


async def run(ctx: AgentContext, debt: CareDebt) -> None:
    """Pipeline step: state, up front, exactly what will count as closure.

    Declaring the evidence bar before the outreach goes out is what stops it
    being renegotiated afterwards.
    """
    with timed(ctx, AGENT, "closure criteria") as step:
        criteria = closure_criteria(debt)
        ctx.shared["closure_criteria"] = criteria
        step["summary"] = (
            "Closure requires "
            + " or ".join(criteria["in_plain_words"])
            + ". Outreach alone will not close this obligation."
        )
        step["detail"] = criteria


def close_with_evidence(
    ctx: AgentContext, debt: CareDebt, evidence: EvidenceItem
) -> dict[str, Any]:
    """Apply a verified closure and write it to the signed ledger."""
    decision = adjudicate(debt, evidence)
    if not decision["accepted"]:
        return decision

    debt.evidence.append(evidence)
    debt.status = DebtStatus.CLOSED
    plan = ctx.shared.get("plan")
    counterfactual = (plan.counterfactual if plan else {}) or {}
    payload: dict[str, Any] = {
        "condition": debt.condition,
        "required_action": debt.required_action,
        "evidence_kinds": sorted({item.kind for item in debt.evidence}),
        "days_open": (evidence.recorded_at.date() - debt.opened_on).days,
        "days_to_deadline": debt.days_to_deadline(evidence.recorded_at.date()),
        "risk_score": debt.risk_score,
        "corroborated": evidence.corroborated,
        "panchayat_code": ctx.person(debt).panchayat,
    }
    if plan is not None:
        payload.update(
            {
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
            }
        )
    entry = ctx.ledger.append(
        "debt_closed",
        person_id=debt.person_id,
        debt_id=debt.id,
        payload=payload,
    )
    decision["ledger_entry"] = entry
    decision["label"] = cal.HUMAN_LABEL.get(debt.condition, debt.condition)
    return decision
