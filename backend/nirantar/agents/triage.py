"""Triage agent: which obligation matters most, right now.

A block carries thousands of open care debts and has the staff to chase a
few hundred a week. Something has to decide the order. Today that decision
is made by whoever happens to walk into the clinic, which is a lottery
weighted towards the people with the fewest barriers -- exactly backwards.

This agent ranks by expected harm if the debt is never closed: clinical
severity, how close the clinical deadline is, and how vulnerable the person
is. The arithmetic is deterministic and auditable. Claude is then given the
case and allowed to adjust the score within a hard band, which lets it catch
clinical gestalt the formula misses (a presumptive TB case in a household
with a small child, say) without ever being able to bury a critical case.
"""

from __future__ import annotations

from typing import Any

from .. import calibration as cal
from ..llm import bounded_float, bounded_text, complete_json
from ..models import CareDebt, DebtStatus
from .base import AgentContext, timed

AGENT = "Triage"

# The model may move a score by at most this much, in either direction.
# Clinical ordering is not something we hand to a language model unbounded.
MAX_LLM_ADJUSTMENT = 12.0

SYSTEM = """You are the triage component of Nirantar, a care-continuity system \
for Indian primary health care. You are given one open care obligation -- an \
abnormal screening result that has not yet led to care -- together with the \
patient's circumstances and a deterministic risk score already computed from \
clinical severity, deadline proximity and vulnerability.

Your job is to sanity-check that score as an experienced district medical \
officer would, and to explain the case in one or two plain sentences that a \
block medical officer could read at a glance.

Reply with JSON only:
{"adjustment": <number between -12 and 12>,
 "rationale": "<= 300 characters, plain English, no hedging>",
 "clinical_flags": ["<short phrase>", ...]}

Adjust upward only for genuine clinical escalators the formula cannot see \
(household transmission risk, pregnancy interacting with the condition, \
likely rapid deterioration). Adjust downward only when the case is plainly \
less urgent than the score implies. Default to 0. You are advising, not \
deciding: the system clamps your adjustment and keeps its own ordering for \
anything critical."""


def deterministic_score(ctx: AgentContext, debt: CareDebt) -> tuple[float, dict[str, Any]]:
    person = ctx.person(debt)
    severity = cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0)
    deadline_days = cal.CLINICAL_DEADLINE_DAYS.get(debt.condition, 30)
    remaining = debt.days_to_deadline(ctx.as_of)

    # Urgency climbs as the deadline approaches and keeps climbing after it
    # passes -- a breached obligation does not become less important, which
    # is precisely the mistake a simple due-date queue makes.
    if remaining < 0:
        urgency = 1.7 + min(1.0, abs(remaining) / (deadline_days * 3))
    else:
        urgency = 1.0 + 0.8 * (1.0 - min(1.0, remaining / max(1, deadline_days)))

    vulnerability = 1.0
    reasons: list[str] = []
    if person.is_pregnant:
        vulnerability += 0.35
        reasons.append("pregnant")
    if person.age <= 5:
        vulnerability += 0.40
        reasons.append("under five")
    if person.age >= 65:
        vulnerability += 0.20
        reasons.append("elderly")
    if person.km_to_district > 30:
        vulnerability += 0.15
        reasons.append("remote village")
    if person.daily_wage_inr and person.daily_wage_inr < 350:
        vulnerability += 0.15
        reasons.append("low daily wage")
    if person.phone_type.value == "none":
        vulnerability += 0.12
        reasons.append("no phone")
    if person.literacy == "none":
        vulnerability += 0.08
        reasons.append("cannot read")
    if len(person.comorbidities) >= 2:
        vulnerability += 0.15
        reasons.append("multiple conditions")

    raw = severity * urgency * vulnerability
    # Normalise onto 0-100 against the worst realistic case.
    score = min(100.0, round(raw / 0.21, 1))
    return score, {
        "severity_daly_weight": severity,
        "urgency_multiplier": round(urgency, 3),
        "vulnerability_multiplier": round(vulnerability, 3),
        "days_to_deadline": remaining,
        "breached": remaining < 0,
        "vulnerability_reasons": reasons,
        "formula": "min(100, severity x urgency x vulnerability / 0.21)",
    }


def _is_critical(debt: CareDebt) -> bool:
    return debt.condition in {
        "tb_confirmed_not_initiated",
        "child_sam_suspect",
        "anaemia_pregnancy_severe",
    }


async def run(ctx: AgentContext, debt: CareDebt) -> None:
    with timed(ctx, AGENT, "risk ranking") as step:
        base_score, detail = deterministic_score(ctx, debt)
        person = ctx.person(debt)
        label = cal.HUMAN_LABEL.get(debt.condition, debt.condition)

        rationale = (
            f"{label}. {'Past' if detail['breached'] else str(detail['days_to_deadline']) + ' days to'} "
            f"clinical deadline"
            + (f"; {', '.join(detail['vulnerability_reasons'])}." if detail["vulnerability_reasons"] else ".")
        )
        final_score = base_score
        flags: list[str] = []
        used_llm = False
        overrides: list[str] = []

        prompt = (
            f"Condition: {label} ({debt.condition})\n"
            f"Required action: {debt.required_action}\n"
            f"Opened: {debt.opened_on.isoformat()} "
            f"({(ctx.as_of - debt.opened_on).days} days ago)\n"
            f"Clinical deadline: {debt.deadline_on.isoformat()} "
            f"({detail['days_to_deadline']} days from today)\n"
            f"Patient: {person.age}-year-old {person.sex}, "
            f"{'pregnant, ' if person.is_pregnant else ''}"
            f"occupation {person.occupation}, daily wage Rs {person.daily_wage_inr:.0f}\n"
            f"Village: {person.village} ({person.km_to_district:.0f} km from district hospital, "
            f"{person.km_to_phc:.0f} km from the PHC)\n"
            f"Literacy: {person.literacy}; phone: {person.phone_type.value}; "
            f"speaks {person.language}\n"
            f"Caregiver available: {person.caregiver_available}\n"
            f"Prior care obligations successfully closed: {person.prior_closures}\n"
            f"Deterministic risk score: {base_score} / 100\n"
            f"Score components: {detail}\n"
        )
        response = await complete_json(system=SYSTEM, prompt=prompt, max_tokens=600)
        if response is not None:
            used_llm = True
            adjustment, note = bounded_float(
                response.get("adjustment"),
                low=-MAX_LLM_ADJUSTMENT,
                high=MAX_LLM_ADJUSTMENT,
                default=0.0,
            )
            if note:
                overrides.append(f"triage adjustment: {note}")
            # A critical condition can be pushed up but never down. The
            # model does not get to de-prioritise a confirmed TB case.
            if _is_critical(debt) and adjustment < 0:
                overrides.append(
                    "negative adjustment refused: condition is on the "
                    "critical list and may only be escalated"
                )
                adjustment = 0.0
            final_score = min(100.0, max(0.0, round(base_score + adjustment, 1)))
            rationale = bounded_text(
                response.get("rationale"), max_chars=300, default=rationale
            )
            raw_flags = response.get("clinical_flags")
            if isinstance(raw_flags, list):
                flags = [str(item)[:60] for item in raw_flags[:5]]
            detail["llm_adjustment"] = adjustment

        debt.risk_score = final_score
        debt.risk_rationale = rationale
        if detail["breached"] and debt.status == DebtStatus.OPEN:
            debt.status = DebtStatus.ESCALATED

        detail["clinical_flags"] = flags
        detail["deterministic_score"] = base_score
        detail["final_score"] = final_score
        detail["safety_overrides"] = overrides
        ctx.shared["triage"] = detail
        ctx.shared.setdefault("safety_overrides", []).extend(overrides)
        step["summary"] = (
            f"Risk {final_score}/100 — {label}; "
            + (
                f"{abs(detail['days_to_deadline'])} days past deadline"
                if detail["breached"]
                else f"{detail['days_to_deadline']} days to deadline"
            )
        )
        step["detail"] = detail
        step["used_llm"] = used_llm
