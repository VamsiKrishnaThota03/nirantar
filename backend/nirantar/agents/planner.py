"""Planner agent: the cheapest path that still discharges the obligation.

This is where Nirantar earns its keep. Given a ranked obligation, a priced
set of barriers, and an inventory of what the system can actually offer, the
planner solves a small constrained optimisation: maximise the chance the
patient actually receives care, while spending as little of the patient's
money and as little of the system's scarcest capacity as possible, and never
missing the clinical deadline.

Three things it refuses to do, enforced in code rather than in a prompt:

* It will not route someone to a facility that cannot dispense what they
  need. A wasted trip is worse than no trip -- it teaches a family that the
  health system wastes their time, and that lesson outlives the illness.
* It will not spend a district-hospital specialist slot on something a
  mobile van can do. Those slots are the scarcest resource in the block, and
  the people who need them most are the ones who lose when they are spent
  carelessly.
* It will not accept a plan that misses the clinical deadline when one
  exists that does not, however much cheaper the late option looks.

Claude chooses between the shortlisted plans and writes the outreach, which
is work that genuinely benefits from a language model. It cannot invent a
plan, cannot select an option the arithmetic rejected, and cannot overrule a
deadline. Every such intervention is recorded on the plan as a safety
override and shown in the dashboard.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from .. import calibration as cal
from ..behaviour import (
    AttendanceFeatures,
    estimate_cost,
    language_is_supported,
    no_show_probability,
)
from ..data.generator import CONDITION_DRUG, DRUG_LABEL
from ..ivr.scripts import (
    build_asha_task_card,
    build_sms_fallback,
    build_voice_script,
    build_whatsapp_message,
)
from ..llm import bounded_text, complete_json
from ..models import (
    CarePlan,
    CareDebt,
    CostBreakdown,
    DebtStatus,
    FacilityType,
    PlanStep,
)
from .base import AgentContext, timed

AGENT = "Planner"

# How scarce each rung of the system is, in arbitrary units of "system cost".
# A district specialist slot is twenty times as precious as a van visit, and
# the planner is the only part of Indian primary care that currently prices
# that difference at all.
SYSTEM_COST: dict[str, float] = {
    FacilityType.TELECONSULT.value: 0.05,
    FacilityType.MOBILE_VAN.value: 0.10,
    FacilityType.SUBCENTRE.value: 0.12,
    FacilityType.PHC.value: 0.35,
    FacilityType.CHC.value: 0.65,
    FacilityType.DISTRICT.value: 1.00,
}

ASHA_ESCORT_SYSTEM_COST = 0.30

BRING_ITEMS: dict[str, list[str]] = {
    "hypertension_suspect": ["health card", "any medicines you take"],
    "hypertension_refill_due": ["health card", "empty medicine strip"],
    "diabetes_suspect": ["health card"],
    "diabetes_refill_due": ["health card", "empty medicine strip"],
    "tb_pulmonary_suspect": ["health card", "previous test slip"],
    "tb_confirmed_not_initiated": ["health card", "test report"],
    "anaemia_pregnancy_severe": ["health card", "mother and child protection card"],
    "anaemia_pregnancy_moderate": ["mother and child protection card"],
    "anc_visit_overdue": ["mother and child protection card"],
    "immunisation_overdue": ["child immunisation card"],
    "child_sam_suspect": ["child immunisation card"],
}

SYSTEM = """You are the planning component of Nirantar, a care-continuity system \
for Indian primary health care.

A deterministic optimiser has already shortlisted up to three care plans for \
one patient. Each has been priced in rupees and working days from the \
patient's point of view, checked against medicine stock and appointment \
capacity, and scored for the probability the patient will not attend. The \
shortlist is final: you may only choose from it.

Your tasks:
1. Choose the plan an experienced district health officer would choose, by \
index. Usually that is the one the optimiser ranked first. Prefer a different \
one only when there is a specific, stated reason the arithmetic cannot see.
2. Write the rationale in two sentences a block medical officer would find \
useful -- concrete, naming the barrier removed and the trade-off accepted.

Reply with JSON only:
{"chosen_index": <integer index from the shortlist>,
 "rationale": "<= 400 characters>",
 "escort_recommended": true | false}

You cannot invent plans, change dates, override medicine availability, or \
select a plan that misses the clinical deadline. The system verifies your \
choice against those constraints and will overrule you, visibly, if it \
violates them."""


def script_language_for(person) -> str:
    """The language the outreach copy will actually be written in."""
    return person.language if language_is_supported(person) else "Hindi"


def _features_for(
    ctx: AgentContext,
    debt: CareDebt,
    option: dict[str, Any],
    *,
    escort: bool,
    text_only: bool,
) -> tuple[CostBreakdown, AttendanceFeatures, float]:
    person = ctx.person(debt)
    ftype = FacilityType(option["facility_type"])
    cost = estimate_cost(person, ftype)
    features = AttendanceFeatures(
        cost=cost,
        days_until_slot=int(option["days_until"]),
        asha_accompanied=escort,
        # Only true where we actually have copy in the patient's language.
        # Asserting it unconditionally would credit the plan with removing a
        # barrier it had not removed -- the Santali speaker who gets a Hindi
        # call has not been reached in their own language, and the model must
        # say so.
        outreach_language_matches=language_is_supported(person),
        expected_stockout=not bool(option.get("stock_ok", True)),
        text_only_outreach=text_only,
    )
    return cost, features, no_show_probability(person, features)


def _score(
    debt: CareDebt,
    option: dict[str, Any],
    cost: CostBreakdown,
    no_show: float,
    *,
    escort: bool,
) -> tuple[float, dict[str, float]]:
    """Lower is better. Every term is in comparable, documented units."""
    severity = cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0)
    # Expected healthy years lost if this plan fails.
    expected_harm = no_show * severity
    # What we are asking the patient to bear, in days of their own earnings.
    patient_burden = 0.6 * cost.share_of_daily_wage
    system_cost = SYSTEM_COST.get(option["facility_type"], 0.5) + (
        ASHA_ESCORT_SYSTEM_COST if escort else 0.0
    )
    # Missing a clinical deadline is not a tunable preference.
    deadline_penalty = 0.0
    if not option.get("within_deadline", False):
        deadline_penalty = 25.0
    total = expected_harm + patient_burden + system_cost + deadline_penalty
    return total, {
        "expected_harm": round(expected_harm, 3),
        "patient_burden": round(patient_burden, 3),
        "system_cost": round(system_cost, 3),
        "deadline_penalty": deadline_penalty,
        "total": round(total, 3),
    }


def shortlist(ctx: AgentContext, debt: CareDebt) -> list[dict[str, Any]]:
    person = ctx.person(debt)
    options: list[dict[str, Any]] = ctx.shared.get("viable_options", [])
    asha = ctx.shared.get("asha")
    asha_capacity = bool(ctx.shared.get("asha_has_capacity"))
    channel = str(ctx.shared.get("preferred_channel", "ivr_call"))
    text_only = bool(ctx.shared.get("preferred_channel_text_only", False))
    drug = CONDITION_DRUG.get(debt.condition)

    candidates: list[dict[str, Any]] = []
    for option in options:
        # Hard constraint: do not send someone for medicine that is not there.
        if debt.required_action == "refill_medication" and not option.get("stock_ok", True):
            continue
        # When the only way to reach this household is a person at the door,
        # the ASHA is not an optional upgrade -- she is the channel. If she
        # has no capacity this week the plan is still clinically sound but
        # the patient cannot be told about it, which run() flags.
        if channel == "asha_visit":
            escort_variants = [True] if (asha_capacity and asha is not None) else [False]
        else:
            escort_variants = [False]
            if asha_capacity and asha is not None:
                escort_variants.append(True)
        for escort in escort_variants:
            cost, features, no_show = _features_for(
                ctx, debt, option, escort=escort, text_only=text_only
            )
            total, parts = _score(debt, option, cost, no_show, escort=escort)
            label = option["label"] + (" with ASHA escort" if escort else "")
            candidates.append(
                {
                    "option": option,
                    "escort": escort,
                    "label": label,
                    "cost": cost,
                    "no_show": no_show,
                    "score": total,
                    "score_parts": parts,
                    "channel": channel,
                    "text_only": text_only,
                    "drug": drug,
                }
            )

    candidates.sort(key=lambda item: item["score"])
    # Keep the best variant per distinct venue so the shortlist offers real
    # alternatives rather than three flavours of the same visit.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        key = str(
            candidate["option"].get("outreach_window_id")
            or candidate["option"].get("facility_id")
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) == 3:
            break
    return deduped


def _build_steps(
    ctx: AgentContext, debt: CareDebt, candidate: dict[str, Any]
) -> list[PlanStep]:
    person = ctx.person(debt)
    option = candidate["option"]
    when = date.fromisoformat(option["on_date"]) if option.get("on_date") else None
    asha = ctx.shared.get("asha")
    steps: list[PlanStep] = []
    order = 1

    # The notification step has to match the channel the patient can actually
    # receive. Telling a household with no handset that we will WhatsApp them
    # is the kind of detail that decides whether a system works.
    channel = candidate["channel"]
    script_language = (
        person.language if language_is_supported(person) else "Hindi"
    )
    if channel == "asha_visit":
        steps.append(
            PlanStep(
                order=order,
                actor="asha",
                action=(
                    f"Visit the household in person to inform them — "
                    f"{person.display_name} has no phone, so there is no "
                    f"electronic way to reach them"
                ),
                where=f"{person.village}",
                on_date=ctx.as_of,
            )
        )
    elif channel == "whatsapp":
        steps.append(
            PlanStep(
                order=order,
                actor="system",
                action=f"Send a WhatsApp message in {script_language}",
                where="outbound",
                on_date=ctx.as_of,
            )
        )
    else:
        steps.append(
            PlanStep(
                order=order,
                actor="system",
                action=(
                    f"Place an automated voice call in {script_language} "
                    f"confirming the appointment"
                    + (
                        f" (no copy available in {person.language} yet)"
                        if script_language != person.language
                        else ""
                    )
                ),
                where="outbound",
                on_date=ctx.as_of,
            )
        )
    order += 1

    if candidate["drug"]:
        steps.append(
            PlanStep(
                order=order,
                actor="facility",
                action=(
                    f"Reserve {DRUG_LABEL.get(candidate['drug'], candidate['drug'])} "
                    f"against this patient so the stock is still there when "
                    f"they arrive"
                ),
                where=option["label"],
                on_date=when,
                facility_id=option.get("facility_id"),
                outreach_window_id=option.get("outreach_window_id"),
            )
        )
        order += 1

    if candidate["escort"] and asha is not None:
        steps.append(
            PlanStep(
                order=order,
                actor="asha",
                action=f"Accompany {person.display_name} to the appointment",
                where=option["where"],
                on_date=when,
            )
        )
        order += 1

    steps.append(
        PlanStep(
            order=order,
            actor="patient",
            action=(
                "Attend the teleconsultation from home"
                if option["facility_type"] == FacilityType.TELECONSULT.value
                else f"Attend at {option['label']}"
            ),
            where=option["where"],
            on_date=when,
            facility_id=option.get("facility_id"),
            outreach_window_id=option.get("outreach_window_id"),
        )
    )
    order += 1

    steps.append(
        PlanStep(
            order=order,
            actor="facility",
            action=(
                "Record the measurement or dispensing event — this is the "
                "evidence that closes the care debt, and nothing else will"
            ),
            where=option["label"],
            on_date=when,
        )
    )
    return steps


async def run(ctx: AgentContext, debt: CareDebt) -> CarePlan | None:
    with timed(ctx, AGENT, "plan optimisation") as step:
        person = ctx.person(debt)
        candidates = shortlist(ctx, debt)
        overrides: list[str] = []

        if not candidates:
            step["summary"] = (
                "No viable plan: no venue can discharge this obligation inside "
                "the clinical deadline with the medicine in stock. Escalating."
            )
            step["detail"] = {
                "options_considered": ctx.shared.get("options", []),
                "conclusion": "escalate_supply_gap",
            }
            ctx.shared["no_viable_plan"] = True
            return None

        chosen_index = 0
        rationale = ""
        used_llm = False

        if len(candidates) > 1:
            shortlist_text = "\n\n".join(
                f"[{index}] {candidate['label']}\n"
                f"    When: {candidate['option'].get('on_date') or 'unscheduled'} "
                f"({candidate['option']['days_until']} days away), "
                f"inside clinical deadline: {candidate['option']['within_deadline']}\n"
                f"    Patient pays: Rs {candidate['cost'].total_inr:.0f} "
                f"({candidate['cost'].share_of_daily_wage:.2f} x daily wage), "
                f"{candidate['cost'].travel_km:.0f} km travel, "
                f"{candidate['cost'].wage_loss_days:.2f} working days lost\n"
                f"    Predicted no-show: {candidate['no_show']:.2f}\n"
                f"    Medicine in stock: {candidate['option'].get('stock_ok')}\n"
                f"    ASHA escort included: {candidate['escort']}\n"
                f"    Optimiser score (lower is better): {candidate['score']:.2f} "
                f"{candidate['score_parts']}"
                for index, candidate in enumerate(candidates)
            )
            prompt = (
                f"Patient: {person.age}-year-old {person.sex}, {person.occupation}, "
                f"daily wage Rs {person.daily_wage_inr:.0f}, "
                f"{'pregnant, ' if person.is_pregnant else ''}"
                f"speaks {person.language}, literacy {person.literacy}, "
                f"village {person.village} ({person.km_to_district:.0f} km from the "
                f"district hospital)\n"
                f"Obligation: {debt.condition} / {debt.required_action}, "
                f"risk score {debt.risk_score}/100, "
                f"{debt.days_to_deadline(ctx.as_of)} days to clinical deadline\n"
                f"Binding constraint identified: {ctx.shared.get('binding_constraint')}\n"
                f"Barrier analysis: {ctx.shared.get('reality_narrative')}\n\n"
                f"Shortlist:\n{shortlist_text}"
            )
            response = await complete_json(system=SYSTEM, prompt=prompt, max_tokens=700)
            if response is not None:
                used_llm = True
                raw_index = response.get("chosen_index")
                try:
                    proposed = int(raw_index)
                except (TypeError, ValueError):
                    proposed = 0
                    overrides.append(
                        f"model returned non-integer plan index {raw_index!r}; "
                        "kept the optimiser's first choice"
                    )
                if not 0 <= proposed < len(candidates):
                    overrides.append(
                        f"model chose index {proposed}, which is not on the "
                        "shortlist; kept the optimiser's first choice"
                    )
                    proposed = 0
                # The model may not trade away a deadline.
                if (
                    not candidates[proposed]["option"].get("within_deadline", False)
                    and candidates[0]["option"].get("within_deadline", False)
                ):
                    overrides.append(
                        "model chose a plan that misses the clinical deadline "
                        "while a compliant plan exists; overruled"
                    )
                    proposed = 0
                # Nor accept a materially worse chance of the patient attending.
                if candidates[proposed]["no_show"] > candidates[0]["no_show"] * 1.25 + 0.02:
                    overrides.append(
                        f"model choice had a {candidates[proposed]['no_show']:.0%} "
                        f"no-show risk against {candidates[0]['no_show']:.0%} for "
                        "the optimiser's choice; overruled"
                    )
                    proposed = 0
                chosen_index = proposed
                rationale = bounded_text(
                    response.get("rationale"), max_chars=400, default=""
                )

        chosen = candidates[chosen_index]
        option = chosen["option"]
        when = date.fromisoformat(option["on_date"]) if option.get("on_date") else None
        asha = ctx.shared.get("asha")
        zero_travel = option["facility_type"] in {
            FacilityType.MOBILE_VAN.value,
            FacilityType.TELECONSULT.value,
        }
        bring = BRING_ITEMS.get(debt.condition, ["health card"])

        baseline = ctx.shared.get("baseline", {})
        baseline_cost = baseline.get("cost", {})

        if not rationale:
            saved = float(baseline_cost.get("total_inr", 0.0)) - chosen["cost"].total_inr
            venue_phrase = (
                "at the patient's doorstep"
                if zero_travel
                else "at the lowest capable facility"
            )
            rationale = (
                f"{chosen['label']} discharges this obligation {venue_phrase}, "
                f"{'inside' if option['within_deadline'] else 'past'} the clinical deadline, "
                f"for ₹{chosen['cost'].total_inr:,.0f} instead of "
                f"₹{float(baseline_cost.get('total_inr', 0)):,.0f} — "
                f"₹{max(0, saved):,.0f} saved for the household and a predicted "
                f"no-show of {chosen['no_show']:.0%} against "
                f"{float(baseline.get('no_show', 0)):.0%} under a conventional referral."
            )

        # Can this patient actually be told about the plan?
        outreach_blocked = chosen["channel"] == "asha_visit" and not (
            asha is not None and chosen["escort"]
        )
        if outreach_blocked:
            overrides.append(
                "patient has no phone and no ASHA has capacity this week, so "
                "there is currently no way to tell them about this plan; "
                "flagged for escalation rather than recorded as outreach"
            )

        voice = build_voice_script(
            person_name=person.display_name,
            condition=debt.condition,
            where=option["where"] if zero_travel else option["label"],
            when=when,
            asha_name=asha.display_name if (chosen["escort"] and asha) else None,
            language=person.language,
            zero_travel=zero_travel,
            bring_items=bring,
        )
        whatsapp = build_whatsapp_message(
            person_name=person.display_name,
            condition=debt.condition,
            where=option["where"] if zero_travel else option["label"],
            when=when,
            asha_name=asha.display_name if (chosen["escort"] and asha) else None,
            language=person.language,
            zero_travel=zero_travel,
        )
        task_card = build_asha_task_card(
            person=person,
            debt=debt,
            plan_label=chosen["label"],
            when=when,
            where=option["where"],
            accompany=bool(chosen["escort"]),
            bring_items=bring,
            risk_score=debt.risk_score,
            binding_constraint=str(ctx.shared.get("binding_constraint", "cost")),
        )

        plan = CarePlan(
            id=f"plan-{uuid.uuid4().hex[:12]}",
            debt_id=debt.id,
            person_id=person.id,
            strategy=chosen["label"],
            steps=_build_steps(ctx, debt, chosen),
            cost=chosen["cost"],
            days_to_closure=int(option["days_until"]),
            predicted_no_show=chosen["no_show"],
            outreach_channel=chosen["channel"],  # type: ignore[arg-type]
            outreach_language=person.language,
            asha_id=asha.id if (chosen["escort"] and asha) else None,
            rationale=rationale,
            safety_overrides=overrides,
            generated_by="llm" if used_llm else "deterministic",
            artifacts={
                # What the outreach actually is, so the interface cannot
                # describe a voice call to someone who has no phone.
                "channel": chosen["channel"],
                "channel_label": {
                    "ivr_call": "automated voice call",
                    "whatsapp": "WhatsApp message",
                    "sms": "SMS",
                    "asha_visit": "ASHA home visit (no phone in the household)",
                }[chosen["channel"]],
                "script_language": script_language_for(person),
                "outreach_blocked": outreach_blocked,
                "voice_script": voice,
                "whatsapp": whatsapp,
                "sms_fallback": build_sms_fallback(
                    when=when, where=option["label"], zero_travel=zero_travel
                ),
                "asha_task_card": task_card,
                "stock_reservation": (
                    {
                        "drug": DRUG_LABEL.get(chosen["drug"], chosen["drug"]),
                        "drug_code": chosen["drug"],
                        "units": 30,
                        "at": option.get("facility_id") or option.get("outreach_window_id"),
                        "note": (
                            "Reserved before the patient is asked to travel. "
                            "An unreserved referral is a coin toss."
                        ),
                    }
                    if chosen["drug"]
                    else None
                ),
            },
            counterfactual={
                "description": baseline.get("description"),
                "facility": baseline.get("facility_name"),
                "cost_inr": baseline_cost.get("total_inr"),
                "travel_km": baseline_cost.get("travel_km"),
                "wage_loss_days": baseline_cost.get("wage_loss_days"),
                "no_show": baseline.get("no_show"),
                "days_until_slot": baseline.get("days_until_slot"),
                "savings_inr": round(
                    max(
                        0.0,
                        float(baseline_cost.get("total_inr", 0.0))
                        - chosen["cost"].total_inr,
                    ),
                    2,
                ),
                "travel_km_avoided": round(
                    max(
                        0.0,
                        float(baseline_cost.get("travel_km", 0.0))
                        - chosen["cost"].travel_km,
                    ),
                    1,
                ),
                "no_show_reduction_pp": round(
                    max(
                        0.0,
                        (float(baseline.get("no_show", 0.0)) - chosen["no_show"]) * 100,
                    ),
                    1,
                ),
            },
        )

        debt.plan_id = plan.id
        if debt.status == DebtStatus.OPEN:
            debt.status = DebtStatus.PLANNED

        # Consume the capacity we just committed. The second patient planned
        # today must see a world in which the first one took a slot.
        window_id = option.get("outreach_window_id")
        if window_id and window_id in ctx.world.outreach:
            ctx.world.outreach[window_id].booked += 1
        facility_id = option.get("facility_id")
        if facility_id and option.get("on_date"):
            facility = ctx.world.facilities.get(facility_id)
            if facility is not None:
                iso = str(option["on_date"])
                if facility.slots.get(iso, 0) > 0:
                    facility.slots[iso] -= 1
        if chosen["escort"] and asha is not None:
            asha.open_tasks += 1

        ctx.shared["plan"] = plan
        ctx.shared["shortlist"] = [
            {
                "label": candidate["label"],
                "score": candidate["score"],
                "score_parts": candidate["score_parts"],
                "cost_inr": candidate["cost"].total_inr,
                "travel_km": candidate["cost"].travel_km,
                "no_show": candidate["no_show"],
                "on_date": candidate["option"].get("on_date"),
                "within_deadline": candidate["option"].get("within_deadline"),
                "chosen": index == chosen_index,
            }
            for index, candidate in enumerate(candidates)
        ]
        ctx.shared.setdefault("safety_overrides", []).extend(overrides)

        step["summary"] = (
            f"{chosen['label']} — ₹{chosen['cost'].total_inr:,.0f} to the household "
            f"({chosen['cost'].travel_km:.0f} km), no-show "
            f"{chosen['no_show']:.0%} vs {float(baseline.get('no_show', 0)):.0%} "
            f"conventional"
        )
        step["detail"] = {
            "shortlist": ctx.shared["shortlist"],
            "chosen_index": chosen_index,
            "rationale": rationale,
            "safety_overrides": overrides,
            "counterfactual": plan.counterfactual,
        }
        step["used_llm"] = used_llm
        return plan
