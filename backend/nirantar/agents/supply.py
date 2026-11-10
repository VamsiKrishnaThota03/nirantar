"""Supply agent: what the health system can actually offer this week.

The reason referrals fail is rarely that no capacity exists. It is that the
capacity that exists is invisible to whoever writes the referral. A mobile
medical unit will be in the patient's own panchayat on Thursday with
amlodipine on board; the referral slip says "district hospital" because the
slip has no idea the van exists.

This agent enumerates every real option that could discharge the obligation
inside its clinical deadline, and checks each one for the three things that
actually determine whether a trip is wasted: does it have the service, does
it have the drug, and does it have a free slot in time.

It is deliberately pure arithmetic and inventory lookup. No language model
touches this step, because capability and stock are facts, and a model that
hallucinated an available slot would send a sick person on a bus for nothing.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..behaviour import expected_stockout
from ..data.generator import CONDITION_ACTION, CONDITION_DRUG
from ..models import CareDebt, FacilityType
from .base import AgentContext, timed

AGENT = "Supply"

# What each required action needs the venue to be able to do.
ACTION_SERVICE: dict[str, list[str]] = {
    "confirm_diagnosis": ["bp", "blood_glucose", "haemoglobin", "mo_consult"],
    "refill_medication": ["dispense"],
    "followup_test": ["sputum_microscopy", "naat", "sputum_collection", "haemoglobin"],
    # Starting TB treatment means registering the patient on the national
    # programme, assigning a treatment supporter and issuing a full regimen.
    # A mobile unit with a medical officer on board is not a substitute for
    # that, so 'mo_consult' is deliberately NOT accepted here -- the cheap
    # option is only allowed to win where it is genuinely equivalent care.
    "initiate_treatment": ["tb_treatment_initiation"],
    "specialist_review": ["specialist_review", "obg", "surgery_opd", "oncology_referral"],
    "routine_visit": ["anc", "immunisation", "bp"],
}

# Actions that can legitimately be completed over a phone line, and those
# that absolutely cannot. A teleconsultation cannot palpate a breast lump,
# and we do not pretend otherwise just because it is cheap.
TELECONSULT_SUFFICIENT = {"refill_medication", "confirm_diagnosis"}
TELECONSULT_NEVER = {"specialist_review", "followup_test", "initiate_treatment"}


def _service_ok(available: list[str], required: list[str]) -> bool:
    if "everything" in available:
        return True
    return any(service in available for service in required)


def _next_free_slot(slots: dict[str, int], not_before: date, not_after: date):
    for iso in sorted(slots):
        try:
            when = date.fromisoformat(iso)
        except ValueError:
            continue
        if when < not_before or when > not_after:
            continue
        if slots[iso] > 0:
            return when
    return None


def enumerate_options(ctx: AgentContext, debt: CareDebt) -> list[dict[str, Any]]:
    person = ctx.person(debt)
    action, ladder = CONDITION_ACTION[debt.condition]
    required_services = ACTION_SERVICE[action]
    drug = CONDITION_DRUG.get(debt.condition)
    # Search up to the deadline, or 21 days out for already-breached debts
    # (a breached obligation still needs the soonest real option).
    horizon = max(ctx.as_of + timedelta(days=21), debt.deadline_on)

    options: list[dict[str, Any]] = []

    # 1. Outreach that comes to the village. Always checked first, because a
    #    zero-travel option changes the economics completely.
    for window in ctx.world.windows_for(person.panchayat, ctx.as_of):
        if window.on_date > horizon:
            break
        if not _service_ok(window.services, required_services):
            continue
        if action == "specialist_review":
            continue  # a van cannot substitute for a specialist
        stock_ok = drug is None or window.carries_stock.get(drug, 0) >= 10
        if action == "refill_medication" and not stock_ok:
            continue
        options.append(
            {
                "kind": window.kind,
                "label": (
                    "Mobile medical unit in "
                    if window.kind == "mobile_van"
                    else "Health camp in "
                )
                + person.panchayat,
                "facility_type": FacilityType.MOBILE_VAN.value,
                "outreach_window_id": window.id,
                "facility_id": None,
                "on_date": window.on_date.isoformat(),
                "days_until": (window.on_date - ctx.as_of).days,
                "within_deadline": window.on_date <= debt.deadline_on,
                "service_ok": True,
                "stock_ok": stock_ok,
                "free_capacity": window.free,
                "where": f"{person.village} / {person.panchayat}",
            }
        )

    # 2. Teleconsultation, where it is clinically sufficient.
    if action in TELECONSULT_SUFFICIENT and action not in TELECONSULT_NEVER:
        tele = ctx.world.facilities.get("tele-00")
        if tele is not None:
            slot = _next_free_slot(tele.slots, ctx.as_of, horizon)
            if slot is not None:
                # A refill still needs physical medicine from somewhere, so a
                # teleconsult is only a complete answer when paired with a
                # local dispensing point that has stock.
                dispenser = None
                if action == "refill_medication" and drug is not None:
                    for facility in ctx.world.facilities_in(person.panchayat):
                        if "dispense" in facility.services and not expected_stockout(
                            facility, drug
                        ):
                            dispenser = facility
                            break
                if action != "refill_medication" or dispenser is not None:
                    options.append(
                        {
                            "kind": "teleconsult",
                            "label": "Teleconsultation"
                            + (
                                f" + dispensing at {dispenser.name}"
                                if dispenser
                                else ""
                            ),
                            "facility_type": FacilityType.TELECONSULT.value,
                            "facility_id": tele.id,
                            "paired_dispenser_id": dispenser.id if dispenser else None,
                            "outreach_window_id": None,
                            "on_date": slot.isoformat(),
                            "days_until": (slot - ctx.as_of).days,
                            "within_deadline": slot <= debt.deadline_on,
                            "service_ok": True,
                            "stock_ok": True,
                            "free_capacity": tele.slots.get(slot.isoformat(), 0),
                            "where": "patient's own home, by phone",
                        }
                    )

    # 3. Fixed facilities, cheapest rung first.
    for ftype in ladder:
        if ftype in {FacilityType.MOBILE_VAN, FacilityType.TELECONSULT}:
            continue
        facility = ctx.world.assigned_facility(person, ftype)
        if facility is None:
            continue
        if not facility.staff_present:
            options.append(
                {
                    "kind": "facility",
                    "label": facility.name,
                    "facility_type": ftype.value,
                    "facility_id": facility.id,
                    "outreach_window_id": None,
                    "on_date": None,
                    "days_until": 999,
                    "within_deadline": False,
                    "service_ok": False,
                    "stock_ok": False,
                    "rejected_because": "no staff currently posted",
                    "free_capacity": 0,
                    "where": facility.panchayat,
                }
            )
            continue
        if not _service_ok(facility.services, required_services):
            continue
        slot = _next_free_slot(facility.slots, ctx.as_of, horizon)
        stock_ok = drug is None or not expected_stockout(facility, drug)
        if slot is None:
            options.append(
                {
                    "kind": "facility",
                    "label": facility.name,
                    "facility_type": ftype.value,
                    "facility_id": facility.id,
                    "outreach_window_id": None,
                    "on_date": None,
                    "days_until": 999,
                    "within_deadline": False,
                    "service_ok": True,
                    "stock_ok": stock_ok,
                    "rejected_because": "no appointment slot inside the clinical deadline",
                    "free_capacity": 0,
                    "where": facility.panchayat,
                }
            )
            continue
        options.append(
            {
                "kind": "facility",
                "label": facility.name,
                "facility_type": ftype.value,
                "facility_id": facility.id,
                "outreach_window_id": None,
                "on_date": slot.isoformat(),
                "days_until": (slot - ctx.as_of).days,
                "within_deadline": slot <= debt.deadline_on,
                "service_ok": True,
                "stock_ok": stock_ok,
                "free_capacity": facility.slots.get(slot.isoformat(), 0),
                "where": facility.panchayat,
            }
        )

    return options


async def run(ctx: AgentContext, debt: CareDebt) -> None:
    with timed(ctx, AGENT, "capacity and stock lookup") as step:
        person = ctx.person(debt)
        options = enumerate_options(ctx, debt)
        viable = [
            option
            for option in options
            if option["service_ok"] and option.get("days_until", 999) < 999
        ]
        asha = ctx.world.asha_for(person)
        asha_has_capacity = bool(
            asha and asha.open_tasks < asha.weekly_visit_capacity
        )
        drug = CONDITION_DRUG.get(debt.condition)

        ctx.shared["options"] = options
        ctx.shared["viable_options"] = viable
        ctx.shared["asha"] = asha
        ctx.shared["asha_has_capacity"] = asha_has_capacity
        ctx.shared["drug_needed"] = drug

        zero_travel = [
            option
            for option in viable
            if option["facility_type"]
            in {FacilityType.MOBILE_VAN.value, FacilityType.TELECONSULT.value}
        ]
        step["summary"] = (
            f"{len(viable)} viable option(s) inside the horizon, "
            f"{len(zero_travel)} of them with no travel for the patient"
            + (
                f"; ASHA {asha.display_name} has capacity"
                if asha_has_capacity and asha
                else "; no ASHA capacity this week"
            )
        )
        step["detail"] = {
            "options": options,
            "rejected": [
                {"label": option["label"], "why": option.get("rejected_because")}
                for option in options
                if option.get("rejected_because")
            ],
            "drug_needed": drug,
            "asha": asha.model_dump() if asha else None,
            "asha_has_capacity": asha_has_capacity,
        }
