"""Reality agent: what would actually happen to this person.

Before proposing anything, Nirantar establishes the baseline honestly. It
constructs the referral a conventional system would issue -- "report to the
Community Health Centre, next available slot, here is an SMS in Hindi" --
prices it, and predicts whether the person will attend.

That prediction is usually bleak, and the bleakness is the finding. It tells
you which barrier is doing the damage, which is what makes the Planner's job
tractable: you are no longer trying to motivate a patient, you are trying to
remove a specific, named, measurable obstacle.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..behaviour import (
    AttendanceFeatures,
    barrier_contributions,
    estimate_cost,
    expected_stockout,
    no_show_probability,
    outreach_channel_for,
)
from ..data.generator import CONDITION_ACTION, CONDITION_DRUG
from ..llm import bounded_text, complete_json
from ..models import CareDebt, FacilityType
from .base import AgentContext, timed

AGENT = "Reality"

SYSTEM = """You are the barrier-analysis component of Nirantar, a care-continuity \
system for Indian primary health care.

You are given one patient, the follow-up a conventional referral system would \
issue them, what that follow-up would cost them in rupees and lost working \
days, and a quantitative decomposition of why they are unlikely to attend.

Write the human truth of this situation for a block medical officer: one short \
paragraph, specific to this person, naming the binding constraint. No \
generalities about awareness or motivation -- the decomposition already tells \
you the real constraint is usually money, distance, time or a drug shelf.

Also name any additional barrier the numbers would miss but that is strongly \
implied by the circumstances (seasonal migration, purdah restrictions on \
travelling alone, a shared handset the patient does not control, a daily-wage \
job with no leave). Only name what the circumstances support.

Reply with JSON only:
{"narrative": "<= 600 characters>",
 "additional_barriers": ["<short phrase>", ...],
 "binding_constraint": "cost" | "distance" | "time" | "stockout" | "language" | "mobility" | "phone_access"}"""

BINDING_CONSTRAINTS = {
    "cost",
    "distance",
    "time",
    "stockout",
    "language",
    "mobility",
    "phone_access",
}


def _next_free_slot(slots: dict[str, int], not_before: date) -> tuple[date | None, int]:
    for iso in sorted(slots):
        try:
            when = date.fromisoformat(iso)
        except ValueError:
            continue
        if when < not_before:
            continue
        if slots[iso] > 0:
            return when, (when - not_before).days
    return None, 999


def conventional_referral(ctx: AgentContext, debt: CareDebt) -> dict[str, Any]:
    """Agent-facing wrapper."""
    return conventional_referral_for(ctx.world, ctx.person(debt), debt, ctx.as_of)


def conventional_referral_for(
    world: Any, person: Any, debt: CareDebt, as_of: date
) -> dict[str, Any]:
    """Reconstruct the referral a normal programme would issue.

    Deliberately not a straw man. It is what a correctly operating referral
    system does today: send the patient to the highest-capability facility
    that can handle the condition, on the next slot that facility has free,
    and notify them by text. Every one of those three choices is defensible
    in isolation and together they produce a no-show.
    """
    _action, ladder = CONDITION_ACTION[debt.condition]
    # Conventional referral goes to the top of the ladder: safest clinically,
    # most expensive for the patient, and nobody has ever measured the
    # trade-off.
    target_type = ladder[-1]
    facility = world.assigned_facility(person, target_type)
    if facility is None:
        facility = world.facilities["dh-00"]
        target_type = FacilityType.DISTRICT

    slot_date, days_until = _next_free_slot(facility.slots, as_of)
    if slot_date is None:
        # No slot inside the horizon: the patient is told to "come and wait".
        days_until = 28
    drug = CONDITION_DRUG.get(debt.condition)
    cost = estimate_cost(person, target_type)
    features = AttendanceFeatures(
        cost=cost,
        days_until_slot=days_until,
        # Conventional referral does not allocate an escort.
        asha_accompanied=False,
        # Default outreach is Hindi, which is not everyone's language.
        outreach_language_matches=(person.language == "Hindi"),
        expected_stockout=expected_stockout(facility, drug),
        # Default outreach is SMS.
        text_only_outreach=True,
    )
    no_show = no_show_probability(person, features)
    return {
        "facility_id": facility.id,
        "facility_name": facility.name,
        "facility_type": target_type.value,
        "slot_date": slot_date.isoformat() if slot_date else None,
        "days_until_slot": days_until,
        "cost": cost.model_dump(),
        "no_show": no_show,
        "channel": "sms",
        "language": "Hindi",
        "expected_stockout": features.expected_stockout,
        "features": {
            "asha_accompanied": False,
            "text_only_outreach": True,
            "outreach_language_matches": features.outreach_language_matches,
        },
        "description": (
            f"Referral slip to {facility.name} "
            f"({cost.travel_km:.0f} km round trip), "
            + (f"slot {slot_date.isoformat()}" if slot_date else "no slot inside 28 days")
            + ", SMS notification in Hindi, no escort, stock not checked."
        ),
    }


async def run(ctx: AgentContext, debt: CareDebt) -> None:
    with timed(ctx, AGENT, "barrier analysis") as step:
        person = ctx.person(debt)
        baseline = conventional_referral(ctx, debt)
        cost = estimate_cost(person, FacilityType(baseline["facility_type"]))
        features = AttendanceFeatures(
            cost=cost,
            days_until_slot=baseline["days_until_slot"],
            asha_accompanied=False,
            outreach_language_matches=baseline["features"]["outreach_language_matches"],
            expected_stockout=baseline["expected_stockout"],
            text_only_outreach=True,
        )
        barriers = barrier_contributions(person, features)
        preferred_channel, text_only = outreach_channel_for(person)

        narrative = (
            f"Under a conventional referral, {person.display_name} would be sent "
            f"{cost.travel_km:.0f} km to {baseline['facility_name']} at a cost of "
            f"₹{cost.total_inr:,.0f} — "
            f"{cost.share_of_daily_wage:.1f} times a day's earnings — "
            f"and has a {baseline['no_show'] * 100:.0f}% predicted chance of not going."
        )
        binding = barriers[0]["barrier"] if barriers else "cost"
        extra: list[str] = []
        used_llm = False

        prompt = (
            f"Patient: {person.age}-year-old {person.sex}, {person.occupation}, "
            f"daily wage Rs {person.daily_wage_inr:.0f}, "
            f"{'pregnant, ' if person.is_pregnant else ''}"
            f"literacy {person.literacy}, speaks {person.language}, "
            f"phone {person.phone_type.value} "
            f"({'own handset' if person.phone_belongs_to_self else 'shares a household handset'}), "
            f"caregiver available: {person.caregiver_available}\n"
            f"Village {person.village}, panchayat {person.panchayat}; "
            f"{person.km_to_subcentre:.0f} km to the sub-centre, "
            f"{person.km_to_phc:.0f} km to the PHC, "
            f"{person.km_to_district:.0f} km to the district hospital\n\n"
            f"Care obligation: {debt.condition}, action required: {debt.required_action}, "
            f"{debt.days_to_deadline(ctx.as_of)} days to clinical deadline\n\n"
            f"Conventional referral: {baseline['description']}\n"
            f"Cost to patient: Rs {cost.total_inr:.0f} "
            f"(Rs {cost.wage_loss_inr:.0f} lost wages over {cost.wage_loss_days} days, "
            f"Rs {cost.fare_inr:.0f} fares, Rs {cost.user_fee_inr:.0f} charges)\n"
            f"Predicted no-show probability: {baseline['no_show']:.2f}\n"
            f"Medicine likely out of stock on arrival: {baseline['expected_stockout']}\n\n"
            f"Quantitative barrier decomposition (log-odds contributions):\n"
            + "\n".join(
                f"  - {item['barrier']}: {item['log_odds']:+.2f} ({item['detail']})"
                for item in barriers
            )
        )
        response = await complete_json(system=SYSTEM, prompt=prompt, max_tokens=700)
        if response is not None:
            used_llm = True
            narrative = bounded_text(
                response.get("narrative"), max_chars=600, default=narrative
            )
            raw = response.get("additional_barriers")
            if isinstance(raw, list):
                extra = [str(item)[:80] for item in raw[:4]]
            candidate = response.get("binding_constraint")
            if isinstance(candidate, str) and candidate in BINDING_CONSTRAINTS:
                binding = candidate

        debt.barriers = [item["barrier"] for item in barriers if item["log_odds"] > 0] + extra
        ctx.shared["baseline"] = baseline
        ctx.shared["barriers"] = barriers
        ctx.shared["binding_constraint"] = binding
        ctx.shared["reality_narrative"] = narrative
        ctx.shared["preferred_channel"] = preferred_channel
        ctx.shared["preferred_channel_text_only"] = text_only

        step["summary"] = (
            f"Conventional referral: ₹{cost.total_inr:,.0f} and "
            f"{cost.travel_km:.0f} km → {baseline['no_show'] * 100:.0f}% predicted no-show. "
            f"Binding constraint: {binding}."
        )
        step["detail"] = {
            "baseline": baseline,
            "barriers": barriers,
            "additional_barriers": extra,
            "binding_constraint": binding,
            "narrative": narrative,
            "preferred_channel": preferred_channel,
        }
        step["used_llm"] = used_llm
