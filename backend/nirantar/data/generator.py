"""Generates a fictional but statistically grounded rural block.

Nothing here describes a real person or a real place. Names, villages and
the district itself are invented. What *is* real is the shape: prevalence
rates, follow-up completion rates, wage levels and travel distances are
drawn from the published figures in ``calibration.py``, so the backlog the
dashboard shows is the backlog a real block of this size would be carrying.

The generated world deliberately starts in a bad state -- thousands of open
care debts, many already past their clinical deadline -- because that is the
honest starting condition of Indian primary care after a decade of
successful mass screening with no closing mechanism. Nirantar's job is to
burn that backlog down, and you cannot demonstrate burning down a backlog
you did not model.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from .. import calibration as cal
from ..models import (
    AshaWorker,
    CareDebt,
    DebtStatus,
    Facility,
    FacilityType,
    Flag,
    OutreachWindow,
    Person,
    PhoneType,
    ScreeningEvent,
)

DISTRICT = "Saryupar"
BLOCK = "Bharatpur"

PANCHAYATS: list[tuple[str, float]] = [
    # (name, km from the panchayat centre to the district hospital)
    ("Amraulia", 11.0),
    ("Bansgaon", 18.5),
    ("Chiraigaon", 7.5),
    ("Dhanauli", 26.0),
    ("Etwa", 33.5),
    ("Gaurihar", 14.0),
    ("Haripur", 41.0),
    ("Jamunaha", 22.0),
    ("Kusmahi", 38.0),
    ("Lakhanpur", 29.0),
    ("Mahuadanr", 47.5),
    ("Nauranga", 9.0),
]

VILLAGE_SUFFIXES = ["", " Khurd", " Buzurg", " Tola", " Bazar", " Pahar", " Ghat"]

GIVEN_NAMES_F = [
    "Sunita", "Kamla", "Rekha", "Phoolmati", "Savitri", "Anita", "Meena",
    "Lalita", "Shanti", "Gayatri", "Rukmini", "Pushpa", "Saroj", "Urmila",
    "Chandrakala", "Nirmala", "Bhagwanti", "Sarita", "Kaushalya", "Munni",
]
GIVEN_NAMES_M = [
    "Ramesh", "Shivkumar", "Dinesh", "Mahendra", "Rajaram", "Chhotelal",
    "Virendra", "Ganesh", "Baijnath", "Sohan", "Prem", "Jagdish", "Harish",
    "Mangal", "Devnarayan", "Suresh", "Kallu", "Raghunath", "Ashok", "Bhola",
]
SURNAMES = [
    "Devi", "Yadav", "Kumar", "Prasad", "Ram", "Pal", "Nishad", "Verma",
    "Chaudhary", "Sahni", "Paswan", "Bind", "Rajbhar", "Maurya", "Kushwaha",
]

LANGUAGES = [
    ("Bhojpuri", 0.46),
    ("Hindi", 0.30),
    ("Awadhi", 0.14),
    ("Maithili", 0.07),
    ("Santali", 0.03),
]

OCCUPATIONS = [
    ("agricultural labourer", 340.0),
    ("marginal farmer", 420.0),
    ("construction labourer", 520.0),
    ("domestic worker", 260.0),
    ("brick kiln worker", 480.0),
    ("petty shopkeeper", 600.0),
    ("migrant worker (seasonal)", 700.0),
    ("homemaker", 0.0),
    ("anganwadi helper", 300.0),
    ("mason", 650.0),
]

DRUGS = [
    "amlodipine_5mg",
    "telmisartan_40mg",
    "metformin_500mg",
    "iron_folic_acid",
    "atd_fdc_adult",
    "ors_zinc",
]

# Human-readable drug names. Internal codes are fine in a database and
# unacceptable in anything a health worker or a patient reads.
DRUG_LABEL = {
    "amlodipine_5mg": "amlodipine 5 mg",
    "telmisartan_40mg": "telmisartan 40 mg",
    "metformin_500mg": "metformin 500 mg",
    "iron_folic_acid": "iron and folic acid tablets",
    "atd_fdc_adult": "anti-TB fixed-dose combination (adult)",
    "ors_zinc": "ORS and zinc",
}

CONDITION_DRUG = {
    "hypertension_suspect": "amlodipine_5mg",
    "hypertension_refill_due": "amlodipine_5mg",
    "diabetes_suspect": "metformin_500mg",
    "diabetes_refill_due": "metformin_500mg",
    "anaemia_pregnancy_severe": "iron_folic_acid",
    "anaemia_pregnancy_moderate": "iron_folic_acid",
    "tb_pulmonary_suspect": "atd_fdc_adult",
    "tb_confirmed_not_initiated": "atd_fdc_adult",
}

# What each condition needs doing, and the lowest rung of the system that can
# actually do it. The second value is the planner's whole opportunity.
CONDITION_ACTION: dict[str, tuple[str, list[FacilityType]]] = {
    "hypertension_suspect": (
        "confirm_diagnosis",
        [FacilityType.SUBCENTRE, FacilityType.MOBILE_VAN, FacilityType.PHC],
    ),
    "hypertension_refill_due": (
        "refill_medication",
        [FacilityType.SUBCENTRE, FacilityType.MOBILE_VAN, FacilityType.PHC],
    ),
    "diabetes_suspect": (
        "confirm_diagnosis",
        [FacilityType.MOBILE_VAN, FacilityType.PHC, FacilityType.CHC],
    ),
    "diabetes_refill_due": (
        "refill_medication",
        [FacilityType.SUBCENTRE, FacilityType.MOBILE_VAN, FacilityType.PHC],
    ),
    "tb_pulmonary_suspect": (
        "followup_test",
        [FacilityType.MOBILE_VAN, FacilityType.PHC, FacilityType.CHC],
    ),
    "tb_confirmed_not_initiated": (
        "initiate_treatment",
        [FacilityType.PHC, FacilityType.CHC],
    ),
    "anaemia_pregnancy_severe": (
        "specialist_review",
        [FacilityType.CHC, FacilityType.DISTRICT],
    ),
    "anaemia_pregnancy_moderate": (
        "refill_medication",
        [FacilityType.SUBCENTRE, FacilityType.MOBILE_VAN],
    ),
    "anc_visit_overdue": (
        "routine_visit",
        [FacilityType.SUBCENTRE, FacilityType.MOBILE_VAN, FacilityType.PHC],
    ),
    "oral_cancer_suspect": (
        "specialist_review",
        [FacilityType.CHC, FacilityType.DISTRICT],
    ),
    "cervical_cancer_suspect": (
        "specialist_review",
        [FacilityType.CHC, FacilityType.DISTRICT],
    ),
    "breast_lump_suspect": (
        "specialist_review",
        [FacilityType.CHC, FacilityType.DISTRICT],
    ),
    "immunisation_overdue": (
        "routine_visit",
        [FacilityType.SUBCENTRE, FacilityType.MOBILE_VAN],
    ),
    "child_sam_suspect": (
        "specialist_review",
        [FacilityType.CHC, FacilityType.DISTRICT],
    ),
}

SCREENING_KIND = {
    "hypertension_suspect": ("bp", "162/98 mmHg", Flag.ABNORMAL),
    "hypertension_refill_due": ("bp", "148/92 mmHg", Flag.ABNORMAL),
    "diabetes_suspect": ("blood_glucose", "214 mg/dl random", Flag.ABNORMAL),
    "diabetes_refill_due": ("blood_glucose", "186 mg/dl random", Flag.ABNORMAL),
    "tb_pulmonary_suspect": ("symptom_screen", "cough > 2 weeks, weight loss", Flag.ABNORMAL),
    "tb_confirmed_not_initiated": ("sputum_naat", "MTB detected, RIF sensitive", Flag.CRITICAL),
    "anaemia_pregnancy_severe": ("haemoglobin", "6.4 g/dl", Flag.CRITICAL),
    "anaemia_pregnancy_moderate": ("haemoglobin", "9.1 g/dl", Flag.ABNORMAL),
    "anc_visit_overdue": ("anc_schedule", "visit 3 not attended", Flag.ABNORMAL),
    "oral_cancer_suspect": ("oral_exam", "non-healing ulcer, tobacco user", Flag.ABNORMAL),
    "cervical_cancer_suspect": ("via_screening", "VIA positive", Flag.ABNORMAL),
    "breast_lump_suspect": ("clinical_breast_exam", "firm 2cm lump, left", Flag.ABNORMAL),
    "immunisation_overdue": ("immunisation_card", "Penta-3 overdue by 9 weeks", Flag.ABNORMAL),
    "child_sam_suspect": ("muac", "11.1 cm MUAC", Flag.CRITICAL),
}


class World:
    """The whole generated block, held in memory and keyed for fast lookup."""

    def __init__(self) -> None:
        self.as_of: date = date.today()
        self.people: dict[str, Person] = {}
        self.facilities: dict[str, Facility] = {}
        self.outreach: dict[str, OutreachWindow] = {}
        self.ashas: dict[str, AshaWorker] = {}
        self.events: dict[str, ScreeningEvent] = {}
        self.debts: dict[str, CareDebt] = {}
        self.seed: int = 0
        # Adults who went through population-based screening at least once.
        # The cascade denominator.
        self.people_screened: int = 0
        self.horizon_days: int = 28

    # --- indexes -----------------------------------------------------------

    def facilities_in(self, panchayat: str) -> list[Facility]:
        return [f for f in self.facilities.values() if f.panchayat == panchayat]

    def facility_of_type(self, ftype: FacilityType) -> list[Facility]:
        return [f for f in self.facilities.values() if f.type == ftype]

    def assigned_facility(self, person: Person, ftype: FacilityType) -> Facility | None:
        """The facility of this tier that serves the person's catchment.

        Not strictly the geographically closest one: Indian public health
        assigns households to a facility by catchment area, and the distance
        used for costing comes from the person's own recorded distance to
        that tier (``km_to_phc`` and friends), exactly as HMIS records it.
        Naming this ``nearest`` would imply a spatial search that neither
        this model nor the real system performs.
        """
        candidates = self.facility_of_type(ftype)
        if not candidates:
            return None
        local = [f for f in candidates if f.panchayat == person.panchayat]
        return (local or candidates)[0]

    def windows_for(self, panchayat: str, after: date) -> list[OutreachWindow]:
        return sorted(
            (
                w
                for w in self.outreach.values()
                if w.panchayat == panchayat and w.on_date >= after and w.free > 0
            ),
            key=lambda w: w.on_date,
        )

    def asha_for(self, person: Person) -> AshaWorker | None:
        for asha in self.ashas.values():
            if person.village in asha.villages:
                return asha
        for asha in self.ashas.values():
            if asha.panchayat == person.panchayat:
                return asha
        return None

    def open_debts(self) -> list[CareDebt]:
        return [
            d
            for d in self.debts.values()
            if d.status in {DebtStatus.OPEN, DebtStatus.PLANNED, DebtStatus.IN_PROGRESS, DebtStatus.ESCALATED}
        ]


def _weighted(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in pairs)
    pick = rng.random() * total
    upto = 0.0
    for name, weight in pairs:
        upto += weight
        if pick <= upto:
            return name
    return pairs[-1][0]


def build_world(
    seed: int = 20260815,
    population: int = 24000,
    as_of: date | None = None,
    horizon_days: int = 28,
) -> World:
    """Generate the block.

    ``horizon_days`` is how far forward appointment slots and mobile-unit
    routes are laid out. The dashboard needs four weeks; a 90-day trial
    simulation needs the whole trial, otherwise the planner runs out of
    capacity to route into and the comparison measures the horizon rather
    than the system.
    """
    rng = random.Random(seed)
    world = World()
    world.seed = seed
    world.horizon_days = horizon_days
    world.as_of = as_of or date.today()
    today = world.as_of

    # --- villages ----------------------------------------------------------
    villages: list[tuple[str, str, float]] = []  # (village, panchayat, km_to_dh)
    for panchayat, km_dh in PANCHAYATS:
        for index in range(rng.randint(3, 5)):
            suffix = VILLAGE_SUFFIXES[index % len(VILLAGE_SUFFIXES)]
            name = f"{panchayat}{suffix}".strip()
            jitter = rng.uniform(-1.5, 4.0)
            villages.append((name, panchayat, max(2.0, km_dh + jitter)))

    # --- facilities --------------------------------------------------------
    for index, (panchayat, _km) in enumerate(PANCHAYATS):
        world.facilities[f"aam-{index:02d}"] = Facility(
            id=f"aam-{index:02d}",
            name=f"Ayushman Arogya Mandir, {panchayat}",
            type=FacilityType.SUBCENTRE,
            panchayat=panchayat,
            services=["bp", "blood_glucose", "haemoglobin", "anc", "immunisation", "dispense"],
            stock={
                drug: rng.choice([0, 0, 4, 12, 30, 60])
                for drug in ["amlodipine_5mg", "iron_folic_acid", "ors_zinc"]
            },
            slots={
                (today + timedelta(days=d)).isoformat(): rng.randint(4, 14)
                for d in range(0, horizon_days)
            },
            staff_present=rng.random() > 0.08,
        )

    phc_panchayats = ["Chiraigaon", "Jamunaha", "Kusmahi"]
    for index, panchayat in enumerate(phc_panchayats):
        world.facilities[f"phc-{index:02d}"] = Facility(
            id=f"phc-{index:02d}",
            name=f"Primary Health Centre, {panchayat}",
            type=FacilityType.PHC,
            panchayat=panchayat,
            services=[
                "bp", "blood_glucose", "haemoglobin", "sputum_microscopy",
                "anc", "dispense", "mo_consult", "tb_treatment_initiation",
            ],
            stock={drug: rng.choice([0, 6, 25, 80, 150]) for drug in DRUGS},
            slots={
                (today + timedelta(days=d)).isoformat(): rng.randint(0, 9)
                for d in range(0, horizon_days)
            },
        )

    world.facilities["chc-00"] = Facility(
        id="chc-00",
        name="Community Health Centre, Bansgaon",
        type=FacilityType.CHC,
        panchayat="Bansgaon",
        services=[
            "bp", "blood_glucose", "haemoglobin", "naat", "xray", "obg",
            "surgery_opd", "dispense", "specialist_review", "tb_treatment_initiation",
        ],
        stock={drug: rng.choice([20, 90, 200, 400]) for drug in DRUGS},
        slots={
            (today + timedelta(days=d)).isoformat(): rng.randint(0, 6)
            for d in range(0, horizon_days)
        },
    )
    world.facilities["dh-00"] = Facility(
        id="dh-00",
        name="District Hospital, Saryupar",
        type=FacilityType.DISTRICT,
        panchayat="Chiraigaon",
        services=[
            "everything", "oncology_referral", "obg", "naat", "ct", "specialist_review",
            "dispense", "tb_treatment_initiation",
        ],
        stock={drug: rng.randint(200, 900) for drug in DRUGS},
        # The district hospital is the bottleneck everyone is referred into.
        slots={
            (today + timedelta(days=d)).isoformat(): rng.randint(0, 3)
            for d in range(0, horizon_days)
        },
    )
    world.facilities["tele-00"] = Facility(
        id="tele-00",
        name="eSanjeevani-style teleconsultation hub",
        type=FacilityType.TELECONSULT,
        panchayat="(virtual)",
        services=["mo_consult", "specialist_review", "prescription"],
        stock={},
        slots={
            (today + timedelta(days=d)).isoformat(): rng.randint(8, 22)
            for d in range(0, horizon_days)
        },
    )

    # --- outreach assets: the thing conventional referral is blind to ------
    window_id = 0
    # The two mobile units do not cover the whole block. In practice the
    # panchayats that get least outreach are the ones furthest from the
    # district headquarters -- the places that need it most. Modelling that
    # inequity is the point; without it the escalation agent has nothing
    # real to find.
    VAN_ROUTE = [
        name
        for name, km in PANCHAYATS
        if name not in {"Mahuadanr", "Haripur", "Kusmahi"}
    ]
    for day_offset in range(0, horizon_days):
        on_date = today + timedelta(days=day_offset)
        if on_date.weekday() == 6:
            continue
        # Two mobile medical units, each covering one panchayat per day.
        for van in range(2):
            panchayat = VAN_ROUTE[(day_offset * 2 + van) % len(VAN_ROUTE)]
            world.outreach[f"van-{window_id:03d}"] = OutreachWindow(
                id=f"van-{window_id:03d}",
                kind="mobile_van",
                panchayat=panchayat,
                on_date=on_date,
                capacity=rng.randint(28, 46),
                booked=0,
                services=[
                    "bp", "blood_glucose", "haemoglobin", "sputum_collection",
                    "anc", "dispense", "mo_consult",
                ],
                carries_stock={
                    "amlodipine_5mg": rng.randint(30, 90),
                    "metformin_500mg": rng.randint(20, 70),
                    "iron_folic_acid": rng.randint(50, 140),
                },
            )
            window_id += 1
        # A weekly Village Health Nutrition Day style camp.
        if on_date.weekday() == 2:
            panchayat = PANCHAYATS[day_offset % len(PANCHAYATS)][0]
            world.outreach[f"camp-{window_id:03d}"] = OutreachWindow(
                id=f"camp-{window_id:03d}",
                kind="health_camp",
                panchayat=panchayat,
                on_date=on_date,
                capacity=rng.randint(60, 110),
                services=["bp", "blood_glucose", "anc", "immunisation", "dispense"],
                carries_stock={"iron_folic_acid": 200, "ors_zinc": 150},
            )
            window_id += 1

    # --- ASHA workers ------------------------------------------------------
    by_panchayat: dict[str, list[str]] = {}
    for village, panchayat, _km in villages:
        by_panchayat.setdefault(panchayat, []).append(village)
    asha_index = 0
    for panchayat, village_list in by_panchayat.items():
        # Roughly one ASHA per 1,000 population, as per NHM norms.
        for chunk_start in range(0, len(village_list), 2):
            chunk = village_list[chunk_start : chunk_start + 2]
            world.ashas[f"asha-{asha_index:03d}"] = AshaWorker(
                id=f"asha-{asha_index:03d}",
                display_name=f"{rng.choice(GIVEN_NAMES_F)} {rng.choice(SURNAMES)}",
                panchayat=panchayat,
                villages=chunk,
                languages=[_weighted(rng, LANGUAGES), "Hindi"],
                open_tasks=rng.randint(0, 9),
                weekly_visit_capacity=rng.randint(18, 30),
                phone_type=PhoneType.SMART if rng.random() > 0.25 else PhoneType.FEATURE,
            )
            asha_index += 1

    # --- people ------------------------------------------------------------
    for serial in range(population):
        village, panchayat, km_dh = villages[serial % len(villages)]
        sex = "female" if rng.random() < 0.504 else "male"
        age = int(min(92, max(0, rng.gauss(29, 19))))
        occupation, base_wage = rng.choice(OCCUPATIONS)
        if age < 15:
            occupation, base_wage = "child", 0.0
        wage = round(max(0.0, rng.gauss(base_wage, base_wage * 0.18)), 0)
        literacy = _weighted(
            rng,
            [("none", 0.26), ("basic", 0.44), ("functional", 0.30)],
        )
        phone = _weighted(
            rng, [("none", 0.11), ("feature", 0.41), ("smart", 0.48)]
        )
        person = Person(
            id=f"p-{serial:06d}",
            display_name=(
                f"{rng.choice(GIVEN_NAMES_F if sex == 'female' else GIVEN_NAMES_M)} "
                f"{rng.choice(SURNAMES)}"
            ),
            age=age,
            sex=sex,  # type: ignore[arg-type]
            panchayat=panchayat,
            village=village,
            language=_weighted(rng, LANGUAGES),
            literacy=literacy,  # type: ignore[arg-type]
            phone_type=PhoneType(phone),
            phone_belongs_to_self=not (sex == "female" and rng.random() < 0.38),
            daily_wage_inr=wage,
            occupation=occupation,
            caregiver_available=rng.random() < 0.55,
            km_to_subcentre=round(max(0.3, rng.gauss(1.8, 0.9)), 1),
            km_to_phc=round(max(1.0, km_dh * rng.uniform(0.25, 0.5)), 1),
            km_to_chc=round(max(2.0, km_dh * rng.uniform(0.45, 0.8)), 1),
            km_to_district=round(km_dh, 1),
            comorbidities=[],
            is_pregnant=(sex == "female" and 18 <= age <= 40 and rng.random() < 0.055),
            prior_closures=rng.choice([0, 0, 0, 1, 1, 2, 3]),
            pseudo_abha=f"SYNTH-{serial:06d}-NOT-A-REAL-ABHA",
        )
        world.people[person.id] = person

    _seed_history(world, rng)
    return world


def _seed_history(world: World, rng: random.Random) -> None:
    """Create 90 days of screening activity and the debts it left behind.

    The ratio matters: we generate a realistic volume of screening and then
    close only as many debts as India actually closes. The residue is the
    backlog, and the backlog is the product's reason to exist.
    """
    today = world.as_of
    event_serial = 0
    debt_serial = 0

    for person in world.people.values():
        conditions, screened = _conditions_for(person, rng)
        if screened:
            world.people_screened += 1
        for condition in conditions:
            # A backlog is not a week old. Population-based screening has
            # been running for years, and obligations from 2024 are still
            # open, which is why the oldest overdue bucket matters.
            days_ago = rng.randint(1, 240)
            opened = today - timedelta(days=days_ago)
            kind, value, flag = SCREENING_KIND[condition]
            facility_pool = world.facilities_in(person.panchayat) or [
                world.facilities["phc-00"]
            ]
            facility = facility_pool[0]
            event = ScreeningEvent(
                id=f"e-{event_serial:07d}",
                person_id=person.id,
                on_date=opened,
                kind=kind,
                value=value,
                flag=flag,
                facility_id=facility.id,
                source=_weighted(
                    rng,
                    [
                        ("aam_screening", 0.55),
                        ("health_camp", 0.20),
                        ("asha_visit", 0.17),
                        ("opd", 0.08),
                    ],
                ),  # type: ignore[arg-type]
            )
            world.events[event.id] = event
            event_serial += 1

            action, _ = CONDITION_ACTION[condition]
            deadline_days = cal.CLINICAL_DEADLINE_DAYS[condition]
            debt = CareDebt(
                id=f"d-{debt_serial:07d}",
                person_id=person.id,
                condition=condition,
                origin_event_id=event.id,
                opened_on=opened,
                deadline_on=opened + timedelta(days=deadline_days),
                required_action=action,  # type: ignore[arg-type]
            )

            # Historical closure, at the rates India actually achieves.
            closed_probability = _historical_closure_probability(condition, person)
            if rng.random() < closed_probability:
                debt.status = DebtStatus.CLOSED
            elif debt.is_breached(today):
                # Past deadline and never closed. Most such debts are, in
                # today's systems, simply invisible.
                debt.status = (
                    DebtStatus.UNREACHABLE if rng.random() < 0.18 else DebtStatus.OPEN
                )
            else:
                debt.status = DebtStatus.OPEN
            world.debts[debt.id] = debt
            debt_serial += 1


ADULT_SCREENING_COVERAGE = 0.55


def _conditions_for(person: Person, rng: random.Random) -> tuple[list[str], bool]:
    """Which abnormal findings this person plausibly has on record.

    Returns the findings plus whether the person was screened at all, because
    the screening cascade needs the denominator -- the people who were tested
    and found normal are the proof that the screening half of the system
    works, and they are the contrast that makes the follow-up failure legible.
    """
    out: list[str] = []
    adult = person.age >= 18
    male = person.sex == "male"
    # One screening encounter covers blood pressure and blood glucose
    # together, as the population-based screening format does.
    screened = adult and rng.random() < ADULT_SCREENING_COVERAGE

    if adult:
        htn_rate = (
            cal.HTN_PREVALENCE_MEN.value if male else cal.HTN_PREVALENCE_WOMEN.value
        )
        if screened and rng.random() < htn_rate:
            out.append(
                "hypertension_refill_due" if rng.random() < 0.34 else "hypertension_suspect"
            )
        dm_rate = (
            cal.HIGH_BLOOD_GLUCOSE_MEN.value
            if male
            else cal.HIGH_BLOOD_GLUCOSE_WOMEN.value
        )
        if screened and rng.random() < dm_rate:
            out.append(
                "diabetes_refill_due" if rng.random() < 0.30 else "diabetes_suspect"
            )
        if rng.random() < 0.012:
            out.append(
                "tb_confirmed_not_initiated" if rng.random() < 0.22 else "tb_pulmonary_suspect"
            )
        if male and rng.random() < 0.006:
            out.append("oral_cancer_suspect")
        if not male and 30 <= person.age <= 59:
            if rng.random() < 0.004:
                out.append("cervical_cancer_suspect")
            if rng.random() < 0.003:
                out.append("breast_lump_suspect")

    if person.is_pregnant:
        if rng.random() < cal.ANAEMIA_PREGNANT_WOMEN.value:
            out.append(
                "anaemia_pregnancy_severe"
                if rng.random() < 0.12
                else "anaemia_pregnancy_moderate"
            )
        if rng.random() < (1 - cal.ANC_FOUR_PLUS_VISITS.value):
            out.append("anc_visit_overdue")

    if person.age <= 2:
        if rng.random() < (1 - cal.FULL_IMMUNISATION_12_23M.value):
            out.append("immunisation_overdue")
    if person.age <= 5 and rng.random() < 0.021:
        out.append("child_sam_suspect")

    return out, screened


def _historical_closure_probability(condition: str, person: Person) -> float:
    """How often this kind of debt gets closed today, without Nirantar.

    Anchored to the published cascade: TB does relatively well because
    NIKSHAY actively chases patients; hypertension and diabetes do terribly
    because after the screening camp packs up, nobody owns the follow-up.
    """
    base = {
        "tb_confirmed_not_initiated": 1.0 - cal.TB_INITIAL_LOSS_TO_FOLLOWUP.value,
        "tb_pulmonary_suspect": 0.62,
        "hypertension_suspect": 0.21,
        "hypertension_refill_due": 0.27,
        "diabetes_suspect": 0.19,
        "diabetes_refill_due": 0.25,
        "anaemia_pregnancy_severe": 0.44,
        "anaemia_pregnancy_moderate": 0.38,
        "anc_visit_overdue": 0.41,
        "oral_cancer_suspect": 0.17,
        "cervical_cancer_suspect": 0.15,
        "breast_lump_suspect": 0.22,
        "immunisation_overdue": 0.52,
        "child_sam_suspect": 0.47,
    }[condition]
    # Distance and poverty both bite.
    if person.km_to_district > 30:
        base *= 0.78
    if person.daily_wage_inr and person.daily_wage_inr < 350:
        base *= 0.85
    if person.phone_type == PhoneType.NONE:
        base *= 0.80
    return max(0.03, min(0.97, base))
