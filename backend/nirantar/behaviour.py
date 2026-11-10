"""What it actually costs a person to attend, and how likely they are to go.

This module is the intellectual core of Nirantar. Conventional referral
software implicitly prices a follow-up visit at zero rupees and zero risk,
then treats non-attendance as the patient's failure of motivation. That
assumption is the reason roughly seven in eight Indian adults with
hypertension do not have it controlled.

Here we price the visit honestly -- lost wages, bus fare, informal charges,
days gone -- and model attendance as a function of that price plus the
barriers the person actually faces. Once attendance is a *predicted
quantity* rather than an assumption, routing becomes an optimisation
problem: find the cheapest path that still discharges the clinical
obligation. That is what the Planner agent does, and it is only possible
because of the arithmetic in this file.

All coefficients are published in ``calibration.py`` with their provenance,
including which ones are assumptions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import calibration as cal
from .models import CostBreakdown, Facility, FacilityType, Person, PhoneType

# Share of a working day consumed by attending at each rung of the system.
# A village-based option costs an hour; a district-hospital trip costs the
# whole day and sometimes the next one too.
WAGE_LOSS_DAYS: dict[FacilityType, float] = {
    FacilityType.TELECONSULT: 0.08,
    FacilityType.MOBILE_VAN: 0.15,
    FacilityType.SUBCENTRE: 0.25,
    FacilityType.PHC: 0.60,
    FacilityType.CHC: 1.00,
    FacilityType.DISTRICT: 1.00,
}

# Registration, tests, and the informal charges that are not supposed to
# exist. Out-of-pocket spending is roughly 47% of all Indian health
# expenditure, so pretending public care is free is not modelling, it is
# wishful thinking.
TYPICAL_USER_FEE_INR: dict[FacilityType, float] = {
    FacilityType.TELECONSULT: 0.0,
    FacilityType.MOBILE_VAN: 0.0,
    FacilityType.SUBCENTRE: 0.0,
    FacilityType.PHC: 25.0,
    FacilityType.CHC: 90.0,
    FacilityType.DISTRICT: 180.0,
}


def _escort_fare_multiplier(person: Person, ftype: FacilityType) -> float:
    """Many patients cannot travel alone, and the escort pays a fare too."""
    if ftype in {FacilityType.TELECONSULT, FacilityType.MOBILE_VAN, FacilityType.SUBCENTRE}:
        return 1.0
    needs_escort = (
        person.age >= 65
        or person.age <= 12
        or person.is_pregnant
        or (person.sex == "female" and person.literacy == "none")
    )
    return 2.0 if needs_escort else 1.0


def estimate_cost(
    person: Person,
    ftype: FacilityType,
    *,
    overnight: bool | None = None,
) -> CostBreakdown:
    km_one_way = person.km_to(ftype)
    wage_days = WAGE_LOSS_DAYS[ftype]
    if overnight is None:
        # Beyond roughly 35 km on rural bus connections, a single appointment
        # realistically consumes two days.
        overnight = ftype == FacilityType.DISTRICT and km_one_way > 35
    if overnight:
        wage_days += 0.8

    # A homemaker or child has no cash wage, but their time is not free: the
    # accompanying earner loses a day. Costing unpaid labour at zero is how
    # women's follow-up gets deprioritised, so we substitute the household
    # casual wage rather than zero.
    effective_wage = (
        person.daily_wage_inr
        if person.daily_wage_inr > 0
        else cal.RURAL_CASUAL_DAILY_WAGE_INR.value * 0.6
    )

    fare = (
        0.0
        if ftype in {FacilityType.TELECONSULT, FacilityType.MOBILE_VAN}
        else 2.0 * km_one_way * cal.BUS_FARE_INR_PER_KM.value
        * _escort_fare_multiplier(person, ftype)
    )
    fee = TYPICAL_USER_FEE_INR[ftype]
    wage_loss = wage_days * effective_wage
    total = wage_loss + fare + fee
    return CostBreakdown(
        wage_loss_days=round(wage_days, 2),
        wage_loss_inr=round(wage_loss, 2),
        fare_inr=round(fare, 2),
        user_fee_inr=round(fee, 2),
        total_inr=round(total, 2),
        travel_km=round(km_one_way * 2, 1),
        share_of_daily_wage=round(total / max(1.0, effective_wage), 2),
    )


@dataclass
class AttendanceFeatures:
    cost: CostBreakdown
    days_until_slot: int
    asha_accompanied: bool
    outreach_language_matches: bool
    expected_stockout: bool
    text_only_outreach: bool


def no_show_probability(person: Person, features: AttendanceFeatures) -> float:
    """Logistic model of not attending. Returns a probability in (0, 1).

    Every term is a barrier someone can actually point at and act on, which
    is the point: the Planner reads the same features and chooses the path
    that zeroes the biggest ones.
    """
    z = cal.NOSHOW_INTERCEPT.value
    z += cal.NOSHOW_W_COST_WAGE_RATIO.value * features.cost.share_of_daily_wage
    z += cal.NOSHOW_W_LOG_DISTANCE.value * math.log1p(features.cost.travel_km)
    z += cal.NOSHOW_W_WAIT_WEEKS.value * (features.days_until_slot / 7.0)
    z += cal.NOSHOW_W_WAGE_LOSS_DAYS.value * features.cost.wage_loss_days
    if features.asha_accompanied:
        z += cal.NOSHOW_W_ASHA_ACCOMPANIED.value
    if not features.outreach_language_matches:
        z += cal.NOSHOW_W_LANGUAGE_MISMATCH.value
    if person.sex == "female" and not person.caregiver_available:
        z += cal.NOSHOW_W_NO_CAREGIVER_FEMALE.value
    if features.expected_stockout:
        z += cal.NOSHOW_W_EXPECTED_STOCKOUT.value
    if features.text_only_outreach:
        z += cal.NOSHOW_W_FEATURE_PHONE_TEXT.value
    # Trust compounds: someone the system has helped before turns up again.
    z += cal.NOSHOW_W_PRIOR_CLOSURE.value * min(3, person.prior_closures)

    probability = 1.0 / (1.0 + math.exp(-z))
    # Never claim certainty in either direction.
    return round(min(0.97, max(0.02, probability)), 4)


def barrier_contributions(person: Person, features: AttendanceFeatures) -> list[dict]:
    """Decompose the no-show prediction into named, actionable barriers.

    Used by the Reality agent and shown in the dashboard, so a decision is
    never a bare number -- the health worker sees *which* barrier dominates
    and therefore what would fix it.
    """
    # Labels are kept short because they are chart categories; the detail
    # string carries the specifics.
    terms = [
        (
            "Cost vs a day's earnings",
            cal.NOSHOW_W_COST_WAGE_RATIO.value * features.cost.share_of_daily_wage,
            f"₹{features.cost.total_inr:,.0f} against a daily wage of "
            f"₹{person.daily_wage_inr:,.0f}",
        ),
        (
            "Distance",
            cal.NOSHOW_W_LOG_DISTANCE.value * math.log1p(features.cost.travel_km),
            f"{features.cost.travel_km:.0f} km round trip",
        ),
        (
            "Wait for the slot",
            cal.NOSHOW_W_WAIT_WEEKS.value * (features.days_until_slot / 7.0),
            f"{features.days_until_slot} days away",
        ),
        (
            "Working days lost",
            cal.NOSHOW_W_WAGE_LOSS_DAYS.value * features.cost.wage_loss_days,
            f"{features.cost.wage_loss_days:.2f} days",
        ),
    ]
    if features.expected_stockout:
        terms.append(
            (
                "Medicine likely absent",
                cal.NOSHOW_W_EXPECTED_STOCKOUT.value,
                "A wasted trip teaches people not to make the next one",
            )
        )
    if not features.outreach_language_matches:
        terms.append(
            (
                "Not contacted in their language",
                cal.NOSHOW_W_LANGUAGE_MISMATCH.value,
                f"Patient speaks {person.language}",
            )
        )
    if person.sex == "female" and not person.caregiver_available:
        terms.append(
            (
                "No caregiver to accompany her",
                cal.NOSHOW_W_NO_CAREGIVER_FEMALE.value,
                "Mobility constraint",
            )
        )
    if features.text_only_outreach:
        terms.append(
            (
                "Text-only outreach",
                cal.NOSHOW_W_FEATURE_PHONE_TEXT.value,
                f"Literacy: {person.literacy}, phone: {person.phone_type.value}",
            )
        )
    if features.asha_accompanied:
        terms.append(
            (
                "ASHA accompanies her (protective)"
                if person.sex == "female"
                else "ASHA accompanies him (protective)",
                cal.NOSHOW_W_ASHA_ACCOMPANIED.value,
                "Single largest modifiable protective factor in the model",
            )
        )
    if person.prior_closures:
        terms.append(
            (
                "Helped before (protective)",
                cal.NOSHOW_W_PRIOR_CLOSURE.value * min(3, person.prior_closures),
                f"{person.prior_closures} prior closures",
            )
        )

    total_abs = sum(abs(weight) for _, weight, _ in terms) or 1.0
    return sorted(
        (
            {
                "barrier": name,
                "log_odds": round(weight, 3),
                "share": round(abs(weight) / total_abs, 3),
                "direction": "increases no-show" if weight > 0 else "reduces no-show",
                "detail": detail,
            }
            for name, weight, detail in terms
        ),
        key=lambda item: -abs(item["log_odds"]),  # type: ignore[arg-type]
    )


def expected_stockout(facility: Facility, drug: str | None) -> bool:
    """Would this patient arrive to find the shelf empty?

    Checked *before* the patient is asked to travel. Routing someone to a
    facility that cannot dispense what they need is the most expensive kind
    of nothing.
    """
    if drug is None:
        return False
    if facility.type in {FacilityType.TELECONSULT}:
        return False
    on_hand = facility.stock.get(drug)
    if on_hand is None:
        return True
    return on_hand < 10


# Languages we have hand-written outreach copy for. Imported from the
# outreach module so there is a single source of truth: claiming we reached
# someone in their own language when we actually fell back to Hindi would
# inflate the predicted attendance by a barrier we had not really removed.
def _supported_languages() -> set[str]:
    from .ivr.scripts import SUPPORTED

    return set(SUPPORTED)


def language_is_supported(person: Person) -> bool:
    return person.language in _supported_languages()


def outreach_channel_for(person: Person) -> tuple[str, bool]:
    """Pick a channel the person can actually use.

    Returns ``(channel, text_only)``. A literacy-blind system defaults to
    SMS and silently excludes a quarter of the adult population; voice is
    the default here and text is the exception.

    Someone with no handset at all cannot be notified electronically by any
    means, so the channel is a human being walking to their door. Pretending
    otherwise is how a system reports 100% outreach coverage while never
    contacting its poorest patients.
    """
    if person.phone_type == PhoneType.NONE or not person.phone_belongs_to_self:
        # A shared handset is not a reliable private channel for health
        # information, and in this setting it usually belongs to a man.
        if person.phone_type == PhoneType.NONE:
            return "asha_visit", False
    if person.literacy == "none":
        return "ivr_call", False
    if person.phone_type == PhoneType.SMART and person.literacy == "functional":
        return "whatsapp", True
    return "ivr_call", False
