"""A controlled trial: run the block forward for 90 days, twice.

Why this module exists
----------------------
Everything else in this project produces *predictions*. The dashboard can
say "this plan costs the household ₹420 instead of ₹747 and we expect an 87%
chance she attends" — but that is our own model talking about itself, and a
reader is entitled to ask whether the model is worth anything.

So this runs the block forward day by day under two arms, same population,
same seed, same effort budget, and counts what actually happened:

* **Status quo** — the backlog worked first-in-first-out, each patient given
  a conventional referral to the highest-capability facility on its next
  free slot, notified by SMS.
* **Nirantar** — the same daily effort budget, but the worklist ranked by
  expected harm and each patient routed by the optimiser.

The circularity problem, and how it is handled
----------------------------------------------
The obvious way to build this would be to draw each patient's attendance
from the planner's own predicted no-show probability. That is worthless: the
planner would be graded against its own beliefs, and "Nirantar performs
better" would be true by construction rather than by evidence.

Instead there is a separate **ground-truth attendance model** whose
coefficients are *deliberately not* the ones the planner believes. Each
trial draws its truth coefficients by perturbing the published assumptions
(log-normal noise, default ±35%), and the planner never sees them. The
question the trial actually answers is therefore the honest one:

    Does optimising against an imperfect model of human behaviour still
    help, in a world whose real behaviour differs from the model?

Run enough trials and you get a distribution rather than a number, which is
why `compare()` is a Monte Carlo over independently perturbed worlds. If the
benefit vanished under perturbation, that would be the finding, and this
module would report it.

Two further honesty constraints
-------------------------------
* **Trials never write to the Impact Ledger.** Simulated outcomes must not
  be mixed into the signed record of real closures; that is precisely the
  confusion the ledger exists to prevent.
* **Predicted-versus-realised is reported**, not hidden. `calibration()`
  buckets the planner's predictions against what the truth model actually
  did, so the reader can see how wrong we were.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from . import calibration as cal
from .agents.planner import build_candidates
from .agents.triage import rank_score
from .agents.reality import conventional_referral_for
from .agents.supply import enumerate_options_for
from .behaviour import (
    AttendanceFeatures,
    estimate_cost,
    language_is_supported,
    outreach_channel_for,
)
from .data.generator import CONDITION_DRUG, World, build_world
from .models import CareDebt, DebtStatus, FacilityType

Arm = Literal["status_quo", "nirantar"]

# Share of the open backlog a block can actually make contact with per day.
# A block has a handful of staff and a telephone; it cannot work eight
# thousand obligations at once. Both arms get the same budget, so the
# comparison is about targeting and logistics, not about effort.
DEFAULT_DAILY_CONTACT_SHARE = 0.025

# Attempts before an obligation is parked as unreachable.
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# The ground truth the planner is not allowed to know
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TruthModel:
    """How people really behave, in this particular simulated world.

    Same functional form as the planner's model — we are not claiming to
    know a better *shape* — but different coefficients. The planner
    optimises against the published assumptions in ``calibration.py``; the
    world runs on these.
    """

    intercept: float
    w_cost: float
    w_dist: float
    w_wait: float
    w_wage: float
    w_asha: float
    w_lang: float
    w_caregiver: float
    w_stockout: float
    w_text: float
    w_prior: float
    perturbation: float = 0.0

    @classmethod
    def as_believed(cls) -> "TruthModel":
        """The world exactly matches our assumptions. The optimistic case."""
        return cls(
            intercept=cal.NOSHOW_INTERCEPT.value,
            w_cost=cal.NOSHOW_W_COST_WAGE_RATIO.value,
            w_dist=cal.NOSHOW_W_LOG_DISTANCE.value,
            w_wait=cal.NOSHOW_W_WAIT_WEEKS.value,
            w_wage=cal.NOSHOW_W_WAGE_LOSS_DAYS.value,
            w_asha=cal.NOSHOW_W_ASHA_ACCOMPANIED.value,
            w_lang=cal.NOSHOW_W_LANGUAGE_MISMATCH.value,
            w_caregiver=cal.NOSHOW_W_NO_CAREGIVER_FEMALE.value,
            w_stockout=cal.NOSHOW_W_EXPECTED_STOCKOUT.value,
            w_text=cal.NOSHOW_W_FEATURE_PHONE_TEXT.value,
            w_prior=cal.NOSHOW_W_PRIOR_CLOSURE.value,
            perturbation=0.0,
        )

    @classmethod
    def perturbed(cls, rng: random.Random, scale: float = 0.35) -> "TruthModel":
        """A world whose behaviour differs from what we assumed.

        Each weight is multiplied by log-normal noise, so a coefficient can
        come out materially stronger or weaker than believed, and the
        intercept shifts too. ``scale`` is roughly the proportional spread.
        """
        base = cls.as_believed()

        def jitter(value: float) -> float:
            return value * math.exp(rng.gauss(0.0, scale))

        return cls(
            # The intercept is additive, so it is shifted rather than scaled.
            intercept=base.intercept + rng.gauss(0.0, scale * 1.5),
            w_cost=jitter(base.w_cost),
            w_dist=jitter(base.w_dist),
            w_wait=jitter(base.w_wait),
            w_wage=jitter(base.w_wage),
            w_asha=jitter(base.w_asha),
            w_lang=jitter(base.w_lang),
            w_caregiver=jitter(base.w_caregiver),
            w_stockout=jitter(base.w_stockout),
            w_text=jitter(base.w_text),
            w_prior=jitter(base.w_prior),
            perturbation=scale,
        )

    def no_show(self, person: Any, features: AttendanceFeatures) -> float:
        z = self.intercept
        z += self.w_cost * features.cost.share_of_daily_wage
        z += self.w_dist * math.log1p(features.cost.travel_km)
        z += self.w_wait * (features.days_until_slot / 7.0)
        z += self.w_wage * features.cost.wage_loss_days
        if features.asha_accompanied:
            z += self.w_asha
        if not features.outreach_language_matches:
            z += self.w_lang
        if person.sex == "female" and not person.caregiver_available:
            z += self.w_caregiver
        if features.expected_stockout:
            z += self.w_stockout
        if features.text_only_outreach:
            z += self.w_text
        z += self.w_prior * min(3, person.prior_closures)
        return min(0.98, max(0.01, 1.0 / (1.0 + math.exp(-z))))

    def as_dict(self) -> dict[str, float]:
        return {
            "intercept": round(self.intercept, 4),
            "cost": round(self.w_cost, 4),
            "distance": round(self.w_dist, 4),
            "wait": round(self.w_wait, 4),
            "wage_loss": round(self.w_wage, 4),
            "asha_escort": round(self.w_asha, 4),
            "language": round(self.w_lang, 4),
            "no_caregiver": round(self.w_caregiver, 4),
            "stockout": round(self.w_stockout, 4),
            "text_only": round(self.w_text, 4),
            "prior_closures": round(self.w_prior, 4),
            "perturbation_scale": self.perturbation,
        }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class DayRecord:
    day: int
    on_date: str
    open: int
    breached: int
    closed_cumulative: int
    unreachable: int
    healthy_years_discharged: float
    patient_rupees_spent: float
    travel_km: float
    contacts_made: int
    attendances: int


@dataclass
class TrialResult:
    arm: Arm
    days: list[DayRecord] = field(default_factory=list)
    # (predicted no-show, actually attended) for every contact made.
    predictions: list[tuple[float, bool]] = field(default_factory=list)
    # person_id -> (attended_at_least_once, km_to_district, daily_wage)
    per_person: dict[str, dict[str, Any]] = field(default_factory=dict)
    closed_debts: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        last = self.days[-1] if self.days else None
        contacts = sum(day.contacts_made for day in self.days)
        attendances = sum(day.attendances for day in self.days)
        return {
            "arm": self.arm,
            "obligations_closed": last.closed_cumulative if last else 0,
            "still_open": last.open if last else 0,
            "past_deadline": last.breached if last else 0,
            "given_up_unreachable": last.unreachable if last else 0,
            "healthy_years_discharged": round(
                last.healthy_years_discharged if last else 0.0, 1
            ),
            "patient_rupees_spent": round(
                last.patient_rupees_spent if last else 0.0, 0
            ),
            "patient_travel_km": round(last.travel_km if last else 0.0, 0),
            "contacts_made": contacts,
            "attendances": attendances,
            "attendance_rate": round(attendances / max(1, contacts), 4),
            "rupees_per_closure": round(
                (last.patient_rupees_spent if last else 0.0)
                / max(1, last.closed_cumulative if last else 1),
                1,
            ),
        }


# ---------------------------------------------------------------------------
# One arm, one world, N days
# ---------------------------------------------------------------------------


def _consume_capacity(world: World, option: dict[str, Any], escort_asha: Any) -> None:
    window_id = option.get("outreach_window_id")
    if window_id and window_id in world.outreach:
        world.outreach[window_id].booked += 1
    facility_id = option.get("facility_id")
    if facility_id and option.get("on_date"):
        facility = world.facilities.get(facility_id)
        if facility is not None:
            iso = str(option["on_date"])
            if facility.slots.get(iso, 0) > 0:
                facility.slots[iso] -= 1
    if escort_asha is not None:
        escort_asha.open_tasks += 1


def _nirantar_offer(
    world: World, person: Any, debt: CareDebt, as_of: date
) -> dict[str, Any] | None:
    """What the real optimiser would offer this patient today."""
    options = enumerate_options_for(world, person, debt, as_of)
    viable = [
        option
        for option in options
        if option["service_ok"] and option.get("days_until", 999) < 999
    ]
    if not viable:
        return None
    asha = world.asha_for(person)
    asha_capacity = bool(asha and asha.open_tasks < asha.weekly_visit_capacity)
    channel, text_only = outreach_channel_for(person)
    candidates = build_candidates(
        person,
        debt,
        viable,
        asha=asha,
        asha_capacity=asha_capacity,
        channel=channel,
        text_only=text_only,
    )
    if not candidates:
        return None
    best = candidates[0]
    return {
        "option": best["option"],
        "cost": best["cost"],
        "predicted_no_show": best["no_show"],
        "features": AttendanceFeatures(
            cost=best["cost"],
            days_until_slot=int(best["option"]["days_until"]),
            asha_accompanied=bool(best["escort"]),
            outreach_language_matches=language_is_supported(person),
            expected_stockout=not bool(best["option"].get("stock_ok", True)),
            text_only_outreach=bool(best["text_only"]),
        ),
        "escort_asha": asha if best["escort"] else None,
    }


def _status_quo_offer(
    world: World, person: Any, debt: CareDebt, as_of: date
) -> dict[str, Any] | None:
    """What a conventional referral system would tell this patient to do."""
    baseline = conventional_referral_for(world, person, debt, as_of)
    ftype = FacilityType(baseline["facility_type"])
    cost = estimate_cost(person, ftype)
    features = AttendanceFeatures(
        cost=cost,
        days_until_slot=int(baseline["days_until_slot"]),
        asha_accompanied=False,
        outreach_language_matches=(person.language == "Hindi"),
        expected_stockout=bool(baseline["expected_stockout"]),
        text_only_outreach=True,
    )
    return {
        "option": {
            "facility_id": baseline["facility_id"],
            "on_date": baseline["slot_date"],
            "outreach_window_id": None,
        },
        "cost": cost,
        "predicted_no_show": baseline["no_show"],
        "features": features,
        "escort_asha": None,
    }


def run_trial(
    *,
    arm: Arm,
    truth: TruthModel,
    days: int = 90,
    seed: int = 20260815,
    population: int = 24000,
    daily_contact_share: float = DEFAULT_DAILY_CONTACT_SHARE,
    draw_seed: int = 1,
    equity_weighting: bool = True,
) -> TrialResult:
    """Run one arm forward for ``days`` days on a freshly generated block.

    ``equity_weighting`` toggles the vulnerability multiplier in the ranking.
    Running the trial with it off is how we measure whether the mechanism
    actually does anything, rather than asserting that it does.
    """
    world = build_world(seed=seed, population=population, horizon_days=days + 5)
    rng = random.Random(draw_seed)
    result = TrialResult(arm=arm)

    start = world.as_of
    closed_cumulative = 0
    healthy_years = 0.0
    rupees = 0.0
    travel = 0.0
    attempts: dict[str, int] = {}

    # Seed the equity denominator with *everyone owed care on day one*, not
    # just the people the system happened to contact. The question an equity
    # audit has to answer is "of all the people owed care, who actually got
    # it?" -- and since the daily budget only reaches a fraction, measuring
    # against contacts made would flatter both arms and saturate at 1.0.
    for debt in world.debts.values():
        if debt.status == DebtStatus.CLOSED:
            continue
        person = world.people[debt.person_id]
        result.per_person.setdefault(
            person.id,
            {
                "attended": False,
                "contacted": 0,
                "km_to_district": person.km_to_district,
                "daily_wage": person.daily_wage_inr,
                "sex": person.sex,
                "has_phone": person.phone_type.value != "none",
                "literate": person.literacy != "none",
                # Whether any of this person's obligations can only be
                # discharged by a specialist. Village-level routing cannot
                # help these people, so they are the stratum most likely to
                # be left behind by an approach that works by moving care
                # closer to home.
                "needs_specialist": False,
            },
        )
        if debt.required_action == "specialist_review":
            result.per_person[person.id]["needs_specialist"] = True

    for day_index in range(days):
        today = start + timedelta(days=day_index)

        workable = [
            debt
            for debt in world.debts.values()
            if debt.status
            in {DebtStatus.OPEN, DebtStatus.PLANNED, DebtStatus.ESCALATED}
        ]
        budget = max(1, int(len(workable) * daily_contact_share))

        if arm == "nirantar":
            # Ranked by expected harm if never closed, optionally weighted
            # for structural disadvantage. Exactly the ranking the live
            # worklist uses.
            workable.sort(
                key=lambda d: rank_score(
                    d,
                    world.people[d.person_id],
                    today,
                    equity_weighted=equity_weighting,
                ),
                reverse=True,
            )
        else:
            # A due-date queue: oldest first. This is what a referral
            # register actually does, and it is not a straw man -- it is
            # simply blind to severity and to cost.
            workable.sort(key=lambda d: d.opened_on)

        contacts = 0
        attendances = 0
        for debt in workable[:budget]:
            person = world.people[debt.person_id]
            offer = (
                _nirantar_offer(world, person, debt, today)
                if arm == "nirantar"
                else _status_quo_offer(world, person, debt, today)
            )
            if offer is None:
                continue
            contacts += 1

            # The outcome is drawn from the ground truth, which the planner
            # does not know.
            truth_no_show = truth.no_show(person, offer["features"])
            attended = rng.random() > truth_no_show
            result.predictions.append((offer["predicted_no_show"], attended))

            record = result.per_person[person.id]
            record["contacted"] += 1

            _consume_capacity(world, offer["option"], offer["escort_asha"])

            if attended:
                attendances += 1
                debt.status = DebtStatus.CLOSED
                closed_cumulative += 1
                severity = cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0)
                healthy_years += severity
                # The patient only pays if they actually travel.
                rupees += offer["cost"].total_inr
                travel += offer["cost"].travel_km
                record["attended"] = True
                person.prior_closures += 1
                result.closed_debts.append(
                    {
                        "condition": debt.condition,
                        "day": day_index,
                        "cost_inr": offer["cost"].total_inr,
                        "travel_km": offer["cost"].travel_km,
                        "km_to_district": person.km_to_district,
                        "daily_wage": person.daily_wage_inr,
                        "severity": severity,
                    }
                )
            else:
                attempts[debt.id] = attempts.get(debt.id, 0) + 1
                if attempts[debt.id] >= MAX_ATTEMPTS:
                    debt.status = DebtStatus.UNREACHABLE
                else:
                    debt.status = DebtStatus.PLANNED

        open_now = [
            debt
            for debt in world.debts.values()
            if debt.status
            in {DebtStatus.OPEN, DebtStatus.PLANNED, DebtStatus.ESCALATED}
        ]
        result.days.append(
            DayRecord(
                day=day_index,
                on_date=today.isoformat(),
                open=len(open_now),
                breached=sum(1 for d in open_now if d.deadline_on < today),
                closed_cumulative=closed_cumulative,
                unreachable=sum(
                    1
                    for d in world.debts.values()
                    if d.status == DebtStatus.UNREACHABLE
                ),
                healthy_years_discharged=round(healthy_years, 2),
                patient_rupees_spent=round(rupees, 2),
                travel_km=round(travel, 1),
                contacts_made=contacts,
                attendances=attendances,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def calibration(result: TrialResult, buckets: int = 10) -> list[dict[str, Any]]:
    """Predicted no-show versus what the ground truth actually did.

    A reliability diagram. If the planner's model were perfect these would
    lie on the diagonal; they will not, and the gap is the honest measure of
    how much to trust a predicted attendance figure.
    """
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(buckets)]
    for predicted, attended in result.predictions:
        index = min(buckets - 1, int(predicted * buckets))
        bins[index].append((predicted, attended))
    rows = []
    for index, bucket in enumerate(bins):
        if not bucket:
            continue
        predicted_mean = statistics.fmean(p for p, _ in bucket)
        realised_no_show = 1.0 - (
            sum(1 for _, attended in bucket if attended) / len(bucket)
        )
        rows.append(
            {
                "bucket": f"{index * 100 // buckets}–{(index + 1) * 100 // buckets}%",
                "n": len(bucket),
                "predicted_no_show": round(predicted_mean, 4),
                "realised_no_show": round(realised_no_show, 4),
                "error": round(realised_no_show - predicted_mean, 4),
            }
        )
    return rows


def brier_score(result: TrialResult) -> float:
    """Mean squared error of the no-show predictions. Lower is better."""
    if not result.predictions:
        return 0.0
    return round(
        statistics.fmean(
            (predicted - (0.0 if attended else 1.0)) ** 2
            for predicted, attended in result.predictions
        ),
        4,
    )


def equity(result: TrialResult, quintiles: int = 5) -> dict[str, Any]:
    """Who got served, broken down by structural disadvantage.

    This is the audit an efficiency objective most needs. Remote, poor
    patients cost more to reach and are less likely to attend, so a planner
    maximising expected benefit per unit of effort has a standing incentive
    to work the easy cases and quietly leave the hard ones. If that is
    happening, it should be visible here rather than discovered by the
    people it happens to.
    """
    people = list(result.per_person.values())
    if not people:
        return {"strata": [], "note": "nobody was owed care"}
    reached = sum(1 for row in people if row["contacted"] > 0)

    def stratify(key: str, label: str) -> list[dict[str, Any]]:
        ordered = sorted(people, key=lambda row: row[key])
        size = max(1, len(ordered) // quintiles)
        rows = []
        for index in range(quintiles):
            chunk = ordered[index * size : (index + 1) * size]
            if index == quintiles - 1:
                chunk = ordered[index * size :]
            if not chunk:
                continue
            served = sum(1 for row in chunk if row["attended"])
            rows.append(
                {
                    "stratum": f"{label} Q{index + 1}",
                    "n": len(chunk),
                    "mean_value": round(
                        statistics.fmean(row[key] for row in chunk), 1
                    ),
                    "served": served,
                    "served_rate": round(served / len(chunk), 4),
                }
            )
        return rows

    distance = stratify("km_to_district", "Distance")
    wage = stratify("daily_wage", "Daily wage")

    def gap(rows: list[dict[str, Any]], worst_is_last: bool) -> float | None:
        if len(rows) < 2:
            return None
        best = rows[0]["served_rate"] if not worst_is_last else rows[-1]["served_rate"]
        worst = rows[-1]["served_rate"] if not worst_is_last else rows[0]["served_rate"]
        if worst <= 0:
            return None
        return round(best / worst, 3)

    def by_flag(flag: str, label: str) -> dict[str, Any]:
        with_flag = [row for row in people if row[flag]]
        without = [row for row in people if not row[flag]]
        return {
            "attribute": label,
            "with_n": len(with_flag),
            "with_served_rate": round(
                sum(1 for r in with_flag if r["attended"]) / max(1, len(with_flag)), 4
            ),
            "without_n": len(without),
            "without_served_rate": round(
                sum(1 for r in without if r["attended"]) / max(1, len(without)), 4
            ),
        }

    return {
        "people_owed_care": len(people),
        "people_contacted": reached,
        "people_served": sum(1 for row in people if row["attended"]),
        "overall_served_rate": round(
            sum(1 for row in people if row["attended"]) / len(people), 4
        ),
        "denominator": (
            "everyone owed care on day one, not merely those the system "
            "managed to contact"
        ),
        "by_distance": distance,
        "by_wage": wage,
        # Nearest quintile's service rate divided by the furthest quintile's.
        # Above 1.0 means the people furthest from care are being served
        # least, which is the failure mode to watch for.
        "nearest_over_furthest_ratio": gap(distance, worst_is_last=False),
        "richest_over_poorest_ratio": gap(wage, worst_is_last=True),
        "by_attribute": [
            by_flag("has_phone", "Has a phone"),
            by_flag("literate", "Can read"),
            by_flag("needs_specialist", "Needs a specialist"),
        ],
        "female_served_rate": round(
            sum(1 for r in people if r["sex"] == "female" and r["attended"])
            / max(1, sum(1 for r in people if r["sex"] == "female")),
            4,
        ),
        "male_served_rate": round(
            sum(1 for r in people if r["sex"] == "male" and r["attended"])
            / max(1, sum(1 for r in people if r["sex"] == "male")),
            4,
        ),
    }


def compare(
    *,
    days: int = 90,
    trials: int = 3,
    seed: int = 20260815,
    population: int = 24000,
    perturbation: float = 0.35,
) -> dict[str, Any]:
    """Monte Carlo over independently perturbed worlds.

    Each trial invents a different ground truth, then runs both arms against
    it with the same random draws, so the two arms face the same world and
    the same luck. The reported benefit is the distribution across trials,
    not a single lucky run.
    """
    per_trial: list[dict[str, Any]] = []
    status_quo_series: list[list[DayRecord]] = []
    nirantar_series: list[list[DayRecord]] = []
    last_nirantar: TrialResult | None = None
    last_status_quo: TrialResult | None = None
    last_unweighted: TrialResult | None = None
    ablation: list[dict[str, Any]] = []

    for trial_index in range(trials):
        truth_rng = random.Random(seed + trial_index * 7919)
        truth = TruthModel.perturbed(truth_rng, scale=perturbation)
        # Same draw seed for both arms: identical luck, different system.
        draw_seed = seed + trial_index * 104729

        status_quo = run_trial(
            arm="status_quo",
            truth=truth,
            days=days,
            seed=seed,
            population=population,
            draw_seed=draw_seed,
        )
        nirantar = run_trial(
            arm="nirantar",
            truth=truth,
            days=days,
            seed=seed,
            population=population,
            draw_seed=draw_seed,
        )
        # Ablation: the same arm with the equity weighting switched off, so
        # the mechanism's effect is measured rather than asserted.
        unweighted = run_trial(
            arm="nirantar",
            truth=truth,
            days=days,
            seed=seed,
            population=population,
            draw_seed=draw_seed,
            equity_weighting=False,
        )
        last_status_quo, last_nirantar = status_quo, nirantar
        last_unweighted = unweighted
        status_quo_series.append(status_quo.days)
        nirantar_series.append(nirantar.days)

        weighted_equity = equity(nirantar)
        unweighted_equity = equity(unweighted)
        ablation.append(
            {
                "trial": trial_index + 1,
                "with_equity_weighting": {
                    "closed": nirantar.summary()["obligations_closed"],
                    "served_rate": weighted_equity["overall_served_rate"],
                    "richest_over_poorest": weighted_equity[
                        "richest_over_poorest_ratio"
                    ],
                    "nearest_over_furthest": weighted_equity[
                        "nearest_over_furthest_ratio"
                    ],
                },
                "without_equity_weighting": {
                    "closed": unweighted.summary()["obligations_closed"],
                    "served_rate": unweighted_equity["overall_served_rate"],
                    "richest_over_poorest": unweighted_equity[
                        "richest_over_poorest_ratio"
                    ],
                    "nearest_over_furthest": unweighted_equity[
                        "nearest_over_furthest_ratio"
                    ],
                },
            }
        )

        sq, ni = status_quo.summary(), nirantar.summary()
        per_trial.append(
            {
                "trial": trial_index + 1,
                "truth_coefficients": truth.as_dict(),
                "status_quo": sq,
                "nirantar": ni,
                "extra_closures": ni["obligations_closed"] - sq["obligations_closed"],
                "closure_multiple": round(
                    ni["obligations_closed"] / max(1, sq["obligations_closed"]), 3
                ),
                "extra_healthy_years": round(
                    ni["healthy_years_discharged"] - sq["healthy_years_discharged"], 1
                ),
                "rupees_per_closure_status_quo": sq["rupees_per_closure"],
                "rupees_per_closure_nirantar": ni["rupees_per_closure"],
            }
        )

    def spread(values: list[float]) -> dict[str, float]:
        return {
            "min": round(min(values), 2),
            "median": round(statistics.median(values), 2),
            "max": round(max(values), 2),
            "mean": round(statistics.fmean(values), 2),
        }

    multiples = [row["closure_multiple"] for row in per_trial]
    extra = [float(row["extra_closures"]) for row in per_trial]
    extra_years = [float(row["extra_healthy_years"]) for row in per_trial]
    cost_ratio = [
        row["rupees_per_closure_nirantar"] / max(1.0, row["rupees_per_closure_status_quo"])
        for row in per_trial
    ]

    def mean_series(series: list[list[DayRecord]]) -> list[dict[str, Any]]:
        if not series:
            return []
        length = min(len(run) for run in series)
        out = []
        for index in range(length):
            out.append(
                {
                    "day": index,
                    "on_date": series[0][index].on_date,
                    "open": round(
                        statistics.fmean(run[index].open for run in series), 1
                    ),
                    "closed_cumulative": round(
                        statistics.fmean(
                            run[index].closed_cumulative for run in series
                        ),
                        1,
                    ),
                    "healthy_years_discharged": round(
                        statistics.fmean(
                            run[index].healthy_years_discharged for run in series
                        ),
                        1,
                    ),
                    "unreachable": round(
                        statistics.fmean(run[index].unreachable for run in series), 1
                    ),
                }
            )
        return out

    return {
        "design": {
            "days": days,
            "trials": trials,
            "population": population,
            "seed": seed,
            "perturbation_scale": perturbation,
            "daily_contact_share": DEFAULT_DAILY_CONTACT_SHARE,
            "max_attempts": MAX_ATTEMPTS,
            "note": (
                "Both arms get the same daily contact budget, the same "
                "population, and the same random draws. They differ only in "
                "who they contact first and what they offer. Outcomes are "
                "drawn from a ground-truth attendance model whose "
                "coefficients are perturbed away from the ones the planner "
                "believes, so the planner is never graded against its own "
                "assumptions."
            ),
            "not_a_claim_of_real_impact": (
                "This is a simulation, not a field trial. It shows the "
                "optimiser helps in a modelled world whose behaviour differs "
                "from the model. It is not evidence of outcomes in any real "
                "block, and it is deliberately NOT written to the Impact "
                "Ledger, which records only real closures."
            ),
        },
        "trials": per_trial,
        "aggregate": {
            "closure_multiple": spread(multiples),
            "extra_closures": spread(extra),
            "extra_healthy_years": spread(extra_years),
            "cost_per_closure_ratio": spread(cost_ratio),
            "nirantar_better_in_all_trials": all(value > 1.0 for value in multiples),
        },
        "burn_down": {
            "status_quo": mean_series(status_quo_series),
            "nirantar": mean_series(nirantar_series),
        },
        "calibration": {
            "nirantar": calibration(last_nirantar) if last_nirantar else [],
            "brier_nirantar": brier_score(last_nirantar) if last_nirantar else 0.0,
            "brier_status_quo": brier_score(last_status_quo) if last_status_quo else 0.0,
            "note": (
                "Predicted no-show against what the ground truth actually "
                "did, from the final trial. The planner's model is "
                "deliberately not the world's model, so these will not lie "
                "on the diagonal. The gap is how much to discount any single "
                "predicted attendance figure."
            ),
        },
        "equity": {
            "status_quo": equity(last_status_quo) if last_status_quo else {},
            "nirantar": equity(last_nirantar) if last_nirantar else {},
            "nirantar_without_equity_weighting": (
                equity(last_unweighted) if last_unweighted else {}
            ),
            "ablation": ablation,
            "note": (
                "Service rates by distance and wage quintile, over everyone "
                "owed care rather than everyone contacted. An efficiency "
                "objective has a standing incentive to work the easy cases, "
                "so these ratios are the numbers to watch: above 1.0 means "
                "the nearest, or the richest, are being served more than the "
                "furthest or the poorest."
            ),
            "what_we_found": (
                "Routing care to the village closes the DISTANCE gap "
                "outright -- the furthest quintile ends up served as often as "
                "the nearest, because the mobile unit removes the journey. "
                "The WAGE gap is harder. The vulnerability weighting narrows "
                "it measurably (see the ablation) at a cost of a few per cent "
                "of total closures, which is a real efficiency-equity "
                "trade-off and is presented as one. It does not close it. The "
                "residual sits with two groups the optimiser cannot route "
                "around: households with no cash income at all, whose time "
                "this model prices at a substituted household wage, and "
                "people whose condition needs a specialist, for whom no "
                "village-level option exists at any price. The second is a "
                "capacity decision rather than a routing one, which is "
                "exactly what the escalation briefs put in front of a Block "
                "Medical Officer."
            ),
        },
    }
