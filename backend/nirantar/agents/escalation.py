"""Escalation agent: turn individual failures into one decision a manager can make.

A block medical officer cannot act on eight thousand overdue follow-ups. They
can act on "the mobile unit has not entered Mahuadanr in nineteen days, and
312 obligations there are now past their clinical deadline; here is the route
change that fixes it."

So this agent does the step that reporting dashboards skip: it clusters
unclosable obligations by their *shared cause*, quantifies the harm each
cluster is accumulating, and names the specific administrative action that
would clear it. Then it writes one page.

The distinction that matters: an escalation is raised against a *system
failure*, never against a patient. "Non-compliant patient" is not a category
in this codebase. If a person cannot attend, the plan was wrong.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from .. import calibration as cal
from ..behaviour import expected_stockout
from ..data.generator import CONDITION_ACTION, CONDITION_DRUG, DRUG_LABEL, World
from ..llm import bounded_text, complete_json
from ..models import CareDebt, DebtStatus, Escalation, FacilityType, PhoneType

AGENT = "Escalation"

SYSTEM = """You are the escalation component of Nirantar, a care-continuity \
system for Indian primary health care. You are writing a one-page brief for a \
Block Medical Officer -- a busy clinician-administrator who will read it on a \
phone between consultations.

You are given one cluster of care obligations that cannot be closed, the \
shared system failure causing it, the quantified harm accumulating, and the \
corrective action the optimiser has identified.

Write the brief. Requirements:
- Open with the decision you want, not with background.
- State the numbers plainly; do not inflate them or add any you were not given.
- Name the specific administrative action: a route, a requisition, a posting, \
a slot allocation. Something a BMO can actually authorise this week.
- No blame directed at patients or at frontline workers. The failure is \
structural; say what the structure did.
- Under 220 words. Markdown. No preamble, no sign-off.

Reply with JSON only:
{"headline": "<= 110 characters, the decision requested>",
 "brief_markdown": "<the brief>",
 "systemic_cause": "<short phrase naming the structural failure>"}"""


# Each cause carries the action that actually fixes it. This mapping is the
# difference between a dashboard and an operations tool.
REMEDY: dict[str, str] = {
    "drug_stockout": (
        "Raise an emergency indent for the named drug to the affected "
        "facilities, and load it onto the next mobile-unit run"
    ),
    "no_outreach_coverage": (
        "Add the affected panchayat to the mobile medical unit route within "
        "the next seven days"
    ),
    "specialist_slot_famine": (
        "Allocate a dedicated weekly referral block at the CHC or district "
        "hospital for obligations already past their clinical deadline"
    ),
    "facility_unstaffed": (
        "Post or depute a provider to the unstaffed facility, or formally "
        "redirect its catchment to a named alternative"
    ),
    "asha_capacity_exhausted": (
        "Authorise additional ASHA task payments for this cycle, or "
        "redistribute villages across neighbouring ASHAs"
    ),
    "no_contact_channel": (
        "Schedule a door-to-door sweep for households with no working phone "
        "contact, using the existing village health register"
    ),
}

CAUSE_LABEL: dict[str, str] = {
    "drug_stockout": "Medicine not available where patients were sent",
    "no_outreach_coverage": "Mobile outreach has not reached this panchayat",
    "specialist_slot_famine": "No specialist appointment capacity inside clinical deadlines",
    "facility_unstaffed": "Facility has no provider posted",
    "asha_capacity_exhausted": "Frontline worker capacity exhausted",
    "no_contact_channel": "No working way to contact these households",
}


def diagnose(world: World, debt: CareDebt, as_of: date) -> str | None:
    """Why can this specific obligation not be closed? Returns a cause key."""
    person = world.people[debt.person_id]
    action, ladder = CONDITION_ACTION[debt.condition]
    drug = CONDITION_DRUG.get(debt.condition)

    if person.phone_type == PhoneType.NONE:
        asha = world.asha_for(person)
        if asha is None or asha.open_tasks >= asha.weekly_visit_capacity:
            return "no_contact_channel"

    local = world.facilities_in(person.panchayat)
    if local and not any(facility.staff_present for facility in local):
        return "facility_unstaffed"

    if drug and action == "refill_medication":
        nothing_local = not local or all(
            expected_stockout(facility, drug) for facility in local
        )
        if nothing_local:
            windows = world.windows_for(person.panchayat, as_of)
            if not any(window.carries_stock.get(drug, 0) >= 10 for window in windows):
                return "drug_stockout"

    if action == "specialist_review":
        starved = True
        for ftype in (FacilityType.CHC, FacilityType.DISTRICT):
            facility = world.assigned_facility(person, ftype)
            if facility is None:
                continue
            for iso, free in facility.slots.items():
                try:
                    when = date.fromisoformat(iso)
                except ValueError:
                    continue
                if free > 0 and as_of <= when <= debt.deadline_on:
                    starved = False
                    break
            if not starved:
                break
        if starved:
            return "specialist_slot_famine"

    if not world.windows_for(person.panchayat, as_of):
        return "no_outreach_coverage"

    asha = world.asha_for(person)
    if asha is not None and asha.open_tasks >= asha.weekly_visit_capacity:
        return "asha_capacity_exhausted"

    return None


def cluster(world: World, debts: list[CareDebt], as_of: date) -> list[dict[str, Any]]:
    """Group unclosable obligations by (cause, panchayat)."""
    groups: dict[tuple[str, str], list[CareDebt]] = defaultdict(list)
    for debt in debts:
        if debt.status == DebtStatus.CLOSED:
            continue
        cause = diagnose(world, debt, as_of)
        if cause is None:
            continue
        person = world.people[debt.person_id]
        groups[(cause, person.panchayat)].append(debt)

    clusters: list[dict[str, Any]] = []
    for (cause, panchayat), members in groups.items():
        breached = [debt for debt in members if debt.is_breached(as_of)]
        harm = sum(
            cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0) for debt in members
        )
        condition_counts: dict[str, int] = defaultdict(int)
        drugs: dict[str, int] = defaultdict(int)
        for debt in members:
            condition_counts[debt.condition] += 1
            drug = CONDITION_DRUG.get(debt.condition)
            if drug:
                drugs[DRUG_LABEL.get(drug, drug)] += 1
        clusters.append(
            {
                "cause": cause,
                "cause_label": CAUSE_LABEL[cause],
                "panchayat": panchayat,
                "debt_ids": [debt.id for debt in members],
                "count": len(members),
                "breached_count": len(breached),
                "people_affected": len({debt.person_id for debt in members}),
                "healthy_years_at_stake": round(harm, 1),
                "highest_risk_score": round(
                    max((debt.risk_score for debt in members), default=0.0), 1
                ),
                "conditions": dict(
                    sorted(condition_counts.items(), key=lambda kv: -kv[1])
                ),
                "drugs_implicated": dict(sorted(drugs.items(), key=lambda kv: -kv[1])),
                "remedy": REMEDY[cause],
                "oldest_days_overdue": max(
                    (
                        -debt.days_to_deadline(as_of)
                        for debt in members
                        if debt.is_breached(as_of)
                    ),
                    default=0,
                ),
            }
        )
    # Rank by harm accumulating, not by raw count: 40 untreated TB cases
    # outrank 400 overdue BP rechecks, and a count-ordered list gets that
    # exactly wrong.
    clusters.sort(key=lambda item: -float(item["healthy_years_at_stake"]))
    return clusters


def _fallback_brief(group: dict[str, Any], as_of: date) -> str:
    conditions = ", ".join(
        f"{cal.HUMAN_LABEL.get(key, key)} ({count})"
        for key, count in list(group["conditions"].items())[:4]
    )
    drugs = ", ".join(group["drugs_implicated"].keys()) or "not applicable"
    return (
        f"**Decision requested:** {group['remedy']}.\n\n"
        f"**Where:** {group['panchayat']} panchayat.\n\n"
        f"**What is happening:** {group['count']} care obligations covering "
        f"{group['people_affected']} people cannot be closed because of "
        f"{group['cause_label'].lower()}. {group['breached_count']} are already "
        f"past their clinical deadline, the oldest by "
        f"{group['oldest_days_overdue']} days.\n\n"
        f"**Clinical mix:** {conditions}.\n\n"
        f"**Medicines implicated:** {drugs}.\n\n"
        f"**Cost of inaction:** approximately "
        f"{group['healthy_years_at_stake']} healthy life-years at stake across "
        f"this cluster if these obligations are never discharged.\n\n"
        f"**Note:** this is a supply-side failure. Each of these patients was "
        f"successfully screened and identified; the system then had nothing to "
        f"offer them. Raised automatically on {as_of.isoformat()}."
    )


async def write_brief(group: dict[str, Any], as_of: date) -> Escalation:
    conditions = ", ".join(
        f"{cal.HUMAN_LABEL.get(key, key)}: {count}"
        for key, count in group["conditions"].items()
    )
    headline = (
        f"{group['cause_label']} in {group['panchayat']} — "
        f"{group['breached_count']} obligations past deadline"
    )
    brief = _fallback_brief(group, as_of)
    cause_phrase = group["cause_label"]
    generated_by = "deterministic"

    prompt = (
        f"Cluster cause: {group['cause_label']} ({group['cause']})\n"
        f"Panchayat: {group['panchayat']}\n"
        f"Care obligations in this cluster: {group['count']}\n"
        f"Distinct people affected: {group['people_affected']}\n"
        f"Already past clinical deadline: {group['breached_count']}\n"
        f"Oldest breach: {group['oldest_days_overdue']} days overdue\n"
        f"Highest individual risk score in cluster: {group['highest_risk_score']}/100\n"
        f"Estimated healthy life-years at stake: {group['healthy_years_at_stake']}\n"
        f"Clinical mix: {conditions}\n"
        f"Medicines implicated: {', '.join(group['drugs_implicated']) or 'none'}\n"
        f"Corrective action identified by the optimiser: {group['remedy']}\n"
        f"Today's date: {as_of.isoformat()}\n"
    )
    response = await complete_json(system=SYSTEM, prompt=prompt, max_tokens=900)
    if response is not None:
        generated_by = "llm"
        headline = bounded_text(response.get("headline"), max_chars=110, default=headline)
        brief = bounded_text(
            response.get("brief_markdown"), max_chars=2400, default=brief
        )
        cause_phrase = bounded_text(
            response.get("systemic_cause"), max_chars=120, default=cause_phrase
        )

    return Escalation(
        id=f"esc-{uuid.uuid4().hex[:10]}",
        debt_ids=group["debt_ids"][:500],
        raised_on=as_of,
        to_role="Block Medical Officer",
        panchayat=group["panchayat"],
        headline=headline,
        brief_markdown=brief,
        systemic_cause=cause_phrase,
        generated_by=generated_by,  # type: ignore[arg-type]
    )
