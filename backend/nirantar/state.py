"""Application state: the world, the ledger, and the aggregate views.

The generated block lives in memory and is rebuilt deterministically from a
seed on every start, so the demo is reproducible: the same seed always
produces the same district, the same backlog, the same patient in the same
village. Anything the agents *decide* -- plans, closures, escalations -- is
persisted, because those are the results and losing them to a restart would
make the impact numbers meaningless.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import calibration as cal
from .agents.escalation import diagnose
from .behaviour import (
    AttendanceFeatures,
    estimate_cost,
    expected_stockout,
    no_show_probability,
)
from .config import Settings, get_settings
from .data.generator import (
    BLOCK,
    CONDITION_ACTION,
    CONDITION_DRUG,
    DISTRICT,
    DRUG_LABEL,
    World,
    build_world,
)
from .ledger import Db, ImpactLedger, connect
from .models import (
    CareDebt,
    CarePlan,
    DebtStatus,
    Escalation,
    EvidenceItem,
    FacilityType,
)

log = logging.getLogger("nirantar.state")


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db: Db = connect(settings.db_path)
        self.ledger = ImpactLedger(self.db, settings.ledger_key_path)
        self.world: World = build_world(seed=settings.seed)
        self.as_of: date = self.world.as_of
        self.plans: dict[str, CarePlan] = {}
        self.escalations: dict[str, Escalation] = {}
        self._ensure_schema()
        self._restore()
        if self.ledger.count() == 0:
            self.ledger.append(
                "dataset_initialised",
                person_id="__system__",
                debt_id="__system__",
                payload={"reason": f"seed {settings.seed}"},
            )

    # --- persistence -------------------------------------------------------

    def _ensure_schema(self) -> None:
        self.db.script(
            """
            CREATE TABLE IF NOT EXISTS debt_state (
                debt_id    TEXT PRIMARY KEY,
                status     TEXT NOT NULL,
                risk_score REAL,
                plan_json  TEXT,
                evidence_json TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS escalation (
                id         TEXT PRIMARY KEY,
                raised_on  TEXT NOT NULL,
                json       TEXT NOT NULL
            );
            """
        )

    def _restore(self) -> None:
        rows = self.db.all(
            "SELECT debt_id, status, risk_score, plan_json, evidence_json FROM debt_state"
        )
        restored = 0
        for debt_id, status, risk, plan_json, evidence_json in rows:
            debt = self.world.debts.get(debt_id)
            if debt is None:
                continue
            debt.status = DebtStatus(status)
            if risk is not None:
                debt.risk_score = float(risk)
            if plan_json:
                plan = CarePlan.model_validate_json(plan_json)
                self.plans[plan.id] = plan
                debt.plan_id = plan.id
            if evidence_json:
                debt.evidence = [
                    EvidenceItem.model_validate(item)
                    for item in json.loads(evidence_json)
                ]
            restored += 1
        for (payload,) in self.db.all("SELECT json FROM escalation"):
            esc = Escalation.model_validate_json(payload)
            self.escalations[esc.id] = esc
        if restored:
            log.info("restored %d persisted care-debt states", restored)

    def persist_debt(self, debt: CareDebt) -> None:
        plan = self.plans.get(debt.plan_id or "")
        self.db.run(
            """INSERT INTO debt_state
                 (debt_id, status, risk_score, plan_json, evidence_json, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(debt_id) DO UPDATE SET
                 status=excluded.status,
                 risk_score=excluded.risk_score,
                 plan_json=excluded.plan_json,
                 evidence_json=excluded.evidence_json,
                 updated_at=excluded.updated_at""",
            (
                debt.id,
                debt.status.value,
                debt.risk_score,
                plan.model_dump_json() if plan else None,
                json.dumps([item.model_dump(mode="json") for item in debt.evidence]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def persist_escalation(self, esc: Escalation) -> None:
        self.escalations[esc.id] = esc
        self.db.run(
            "INSERT OR REPLACE INTO escalation (id, raised_on, json) VALUES (?,?,?)",
            (esc.id, esc.raised_on.isoformat(), esc.model_dump_json()),
        )

    def register_plan(self, plan: CarePlan) -> None:
        self.plans[plan.id] = plan

    # --- aggregate views ---------------------------------------------------

    def headline(self) -> dict[str, Any]:
        debts = list(self.world.debts.values())
        by_status: dict[str, int] = defaultdict(int)
        for debt in debts:
            by_status[debt.status.value] += 1
        open_like = [
            debt
            for debt in debts
            if debt.status
            in {DebtStatus.OPEN, DebtStatus.PLANNED, DebtStatus.IN_PROGRESS, DebtStatus.ESCALATED}
        ]
        breached = [debt for debt in open_like if debt.is_breached(self.as_of)]
        harm = sum(
            cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0) for debt in open_like
        )
        return {
            "district": DISTRICT,
            "block": BLOCK,
            "as_of": self.as_of.isoformat(),
            "population_modelled": len(self.world.people),
            "care_debts_total": len(debts),
            "care_debts_open": len(open_like),
            "care_debts_breached": len(breached),
            "care_debts_closed": by_status.get("closed", 0),
            "care_debts_unreachable": by_status.get("unreachable", 0),
            "by_status": dict(by_status),
            "healthy_years_at_stake": round(harm, 1),
            "people_with_open_debt": len({debt.person_id for debt in open_like}),
            "share_of_population_owed_care": round(
                len({debt.person_id for debt in open_like}) / max(1, len(self.world.people)),
                4,
            ),
            "ledger": self.ledger.impact(),
            "demo_mode": self.settings.demo_mode,
            "llm_enabled": self.settings.llm_enabled,
        }

    def cascade(self) -> list[dict[str, Any]]:
        """The status-quo screening cascade: where people are being lost today.

        Deliberately only three stages, and strictly monotonic. This describes
        the world *before* Nirantar touches it -- what the block achieved on
        its own -- so it stays a fixed baseline rather than a number that
        improves while you look at it. Nirantar's own contribution is counted
        separately, in the Impact Ledger, which is the only place a closure
        this system caused can be claimed.
        """
        debts = list(self.world.debts.values())
        closed = sum(1 for debt in debts if debt.status == DebtStatus.CLOSED)
        return [
            {
                "stage": "Screened at least once",
                "count": self.world.people_screened,
                "note": (
                    "Population-based screening is the part India already does "
                    "well, and it works at a scale few countries manage"
                ),
            },
            {
                "stage": "Abnormal result found",
                "count": len(debts),
                # The people who fall out here were screened and found
                # healthy. That is the programme working, not a loss, and
                # labelling it "lost" would be a straightforward lie.
                "drop_is_loss": False,
                "drop_label": "screened and found healthy",
                "note": (
                    "Each one creates an obligation the health system now owes "
                    "a named person, with a clinical deadline"
                ),
            },
            {
                "stage": "Care actually delivered",
                "count": closed,
                "drop_is_loss": True,
                "drop_label": "found to be ill, then lost",
                "note": (
                    "Evidenced by a measurement, a dispensing record or a test "
                    "result -- not by a referral slip or a counselling note"
                ),
            },
        ]

    def aging(self) -> list[dict[str, Any]]:
        buckets = [
            ("Inside deadline", lambda days: days >= 0),
            ("1-7 days overdue", lambda days: -7 <= days < 0),
            ("8-30 days overdue", lambda days: -30 <= days < -7),
            ("31-90 days overdue", lambda days: -90 <= days < -30),
            ("Over 90 days overdue", lambda days: days < -90),
        ]
        open_like = self.world.open_debts()
        out = []
        for label, predicate in buckets:
            members = [
                debt
                for debt in open_like
                if predicate(debt.days_to_deadline(self.as_of))
            ]
            out.append(
                {
                    "bucket": label,
                    "count": len(members),
                    "healthy_years_at_stake": round(
                        sum(
                            cal.SEVERITY_DALY_WEIGHT.get(debt.condition, 2.0)
                            for debt in members
                        ),
                        1,
                    ),
                }
            )
        return out

    def by_condition(self) -> list[dict[str, Any]]:
        counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"open": 0, "closed": 0, "breached": 0}
        )
        for debt in self.world.debts.values():
            entry = counts[debt.condition]
            if debt.status == DebtStatus.CLOSED:
                entry["closed"] += 1
            else:
                entry["open"] += 1
                if debt.is_breached(self.as_of):
                    entry["breached"] += 1
        out = []
        for condition, entry in counts.items():
            total = entry["open"] + entry["closed"]
            out.append(
                {
                    "condition": condition,
                    "label": cal.HUMAN_LABEL.get(condition, condition),
                    "open": entry["open"],
                    "closed": entry["closed"],
                    "breached": entry["breached"],
                    "closure_rate": round(entry["closed"] / max(1, total), 3),
                    "severity_weight": cal.SEVERITY_DALY_WEIGHT.get(condition, 2.0),
                    "deadline_days": cal.CLINICAL_DEADLINE_DAYS.get(condition, 30),
                    "healthy_years_at_stake": round(
                        entry["open"] * cal.SEVERITY_DALY_WEIGHT.get(condition, 2.0), 1
                    ),
                }
            )
        out.sort(key=lambda item: -float(item["healthy_years_at_stake"]))
        return out

    def by_panchayat(self) -> list[dict[str, Any]]:
        population: dict[str, int] = defaultdict(int)
        for person in self.world.people.values():
            population[person.panchayat] += 1
        stats: dict[str, dict[str, Any]] = {
            name: {
                "panchayat": name,
                "population": population[name],
                "open": 0,
                "breached": 0,
                "closed": 0,
                "healthy_years_at_stake": 0.0,
                "people_owed": set(),
            }
            for name in population
        }
        for debt in self.world.debts.values():
            person = self.world.people[debt.person_id]
            entry = stats[person.panchayat]
            if debt.status == DebtStatus.CLOSED:
                entry["closed"] += 1
                continue
            entry["open"] += 1
            entry["people_owed"].add(person.id)
            entry["healthy_years_at_stake"] += cal.SEVERITY_DALY_WEIGHT.get(
                debt.condition, 2.0
            )
            if debt.is_breached(self.as_of):
                entry["breached"] += 1

        today = self.as_of
        out = []
        for entry in stats.values():
            name = entry["panchayat"]
            windows = self.world.windows_for(name, today)
            next_outreach = windows[0].on_date.isoformat() if windows else None
            facilities = self.world.facilities_in(name)
            unstaffed = [f.name for f in facilities if not f.staff_present]
            out.append(
                {
                    "panchayat": name,
                    "population": entry["population"],
                    "open": entry["open"],
                    "breached": entry["breached"],
                    "closed": entry["closed"],
                    "people_owed_care": len(entry["people_owed"]),
                    "open_per_1000": round(
                        entry["open"] / max(1, entry["population"]) * 1000, 1
                    ),
                    "healthy_years_at_stake": round(entry["healthy_years_at_stake"], 1),
                    "next_outreach_visit": next_outreach,
                    "days_until_outreach": (
                        (date.fromisoformat(next_outreach) - today).days
                        if next_outreach
                        else None
                    ),
                    "unstaffed_facilities": unstaffed,
                    "km_to_district_hospital": round(
                        sum(
                            person.km_to_district
                            for person in self.world.people.values()
                            if person.panchayat == name
                        )
                        / max(1, entry["population"]),
                        1,
                    ),
                }
            )
        out.sort(key=lambda item: -float(item["healthy_years_at_stake"]))
        return out

    def supply_gaps(self) -> dict[str, Any]:
        stockouts: list[dict[str, Any]] = []
        for facility in self.world.facilities.values():
            for drug, units in facility.stock.items():
                if units < 10:
                    stockouts.append(
                        {
                            "facility": facility.name,
                            "facility_type": facility.type.value,
                            "panchayat": facility.panchayat,
                            "drug": DRUG_LABEL.get(drug, drug),
                            "units": units,
                        }
                    )
        unstaffed = [
            {"facility": f.name, "panchayat": f.panchayat, "type": f.type.value}
            for f in self.world.facilities.values()
            if not f.staff_present
        ]
        # Panchayats with no outreach inside two weeks: the single most
        # fixable cause of non-closure in the whole model.
        horizon = self.as_of + timedelta(days=14)
        uncovered = []
        for name in {person.panchayat for person in self.world.people.values()}:
            windows = [
                window
                for window in self.world.windows_for(name, self.as_of)
                if window.on_date <= horizon
            ]
            if not windows:
                uncovered.append(name)
        specialist_capacity = 0
        for fid in ("chc-00", "dh-00"):
            facility = self.world.facilities.get(fid)
            if facility:
                specialist_capacity += sum(
                    free
                    for iso, free in facility.slots.items()
                    if self.as_of <= date.fromisoformat(iso) <= horizon
                )
        specialist_demand = sum(
            1
            for debt in self.world.open_debts()
            if CONDITION_ACTION[debt.condition][0] == "specialist_review"
        )
        return {
            "stockouts": sorted(stockouts, key=lambda item: item["units"])[:40],
            "stockout_count": len(stockouts),
            "unstaffed_facilities": unstaffed,
            "panchayats_without_outreach_14d": sorted(uncovered),
            "specialist_slots_next_14d": specialist_capacity,
            "specialist_reviews_owed": specialist_demand,
            "specialist_capacity_ratio": round(
                specialist_capacity / max(1, specialist_demand), 3
            ),
            "asha_overloaded": [
                {
                    "asha": asha.display_name,
                    "panchayat": asha.panchayat,
                    "open_tasks": asha.open_tasks,
                    "capacity": asha.weekly_visit_capacity,
                }
                for asha in self.world.ashas.values()
                if asha.open_tasks >= asha.weekly_visit_capacity
            ],
        }

    def barrier_profile(self, sample: int = 500) -> dict[str, Any]:
        """Aggregate barrier analysis over a sample of open obligations.

        Sampled rather than exhaustive so the dashboard stays responsive;
        the sample size is reported so nobody mistakes it for a census.
        """
        open_like = self.world.open_debts()
        step = max(1, len(open_like) // sample)
        chosen = open_like[::step][:sample]
        totals: dict[str, float] = defaultdict(float)
        cost_total = 0.0
        km_total = 0.0
        noshow_total = 0.0
        for debt in chosen:
            person = self.world.people[debt.person_id]
            _action, ladder = CONDITION_ACTION[debt.condition]
            ftype = ladder[-1]
            facility = self.world.assigned_facility(person, ftype)
            cost = estimate_cost(person, ftype)
            features = AttendanceFeatures(
                cost=cost,
                days_until_slot=14,
                asha_accompanied=False,
                outreach_language_matches=(person.language == "Hindi"),
                expected_stockout=(
                    expected_stockout(facility, CONDITION_DRUG.get(debt.condition))
                    if facility
                    else False
                ),
                text_only_outreach=True,
            )
            noshow_total += no_show_probability(person, features)
            cost_total += cost.total_inr
            km_total += cost.travel_km
            # Short labels: these are chart categories, and a label the axis
            # has to truncate is a label nobody reads.
            if person.language != "Hindi":
                totals["Not a Hindi speaker"] += 1
            if person.km_to_district > 25:
                totals["Over 25 km from hospital"] += 1
            if cost.share_of_daily_wage > 1.0:
                totals["Costs over a day's wage"] += 1
            if person.sex == "female" and not person.caregiver_available:
                totals["Woman, no caregiver"] += 1
            if person.literacy == "none":
                totals["Cannot read an SMS"] += 1
            if not person.phone_belongs_to_self:
                totals["No handset of their own"] += 1
            if features.expected_stockout:
                totals["Medicine likely absent"] += 1
            if person.phone_type.value == "none":
                totals["No phone at all"] += 1
        count = max(1, len(chosen))
        return {
            "sample_size": len(chosen),
            "population_of_open_debts": len(open_like),
            "mean_conventional_cost_inr": round(cost_total / count, 1),
            "mean_conventional_travel_km": round(km_total / count, 1),
            "mean_conventional_no_show": round(noshow_total / count, 4),
            "projected_aggregate_cost_inr": round(
                cost_total / count * len(open_like), 0
            ),
            "barriers": sorted(
                (
                    {
                        "barrier": name,
                        "count": int(value),
                        "share": round(value / count, 3),
                    }
                    for name, value in totals.items()
                ),
                key=lambda item: -int(item["count"]),
            ),
        }

    def blocked_reasons(self, sample: int = 1200) -> list[dict[str, Any]]:
        counts: dict[str, int] = defaultdict(int)
        open_like = self.world.open_debts()
        step = max(1, len(open_like) // sample)
        for debt in open_like[::step][:sample]:
            cause = diagnose(self.world, debt, self.as_of)
            counts[cause or "no_structural_blocker"] += 1
        total = max(1, sum(counts.values()))
        return sorted(
            (
                {"cause": cause, "count": count, "share": round(count / total, 3)}
                for cause, count in counts.items()
            ),
            key=lambda item: -int(item["count"]),
        )


_state: AppState | None = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState(get_settings())
    return _state


def reset_state_for_tests() -> None:
    global _state
    if _state is not None:
        _state.db.close()
    _state = None
