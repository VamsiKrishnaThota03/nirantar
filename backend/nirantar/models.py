"""Nirantar domain model.

Shaped to map cleanly onto HL7 FHIR R4 resources so that a state programme
already running an ABDM-compliant health record system can adopt this without
a data migration. The mapping is noted per class and implemented in
``fhir.py``.

The central object is the **CareDebt**: a single un-discharged obligation the
health system owes a specific person, created the moment an abnormal result
exists and closable only by evidence that care actually happened.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PhoneType(str, enum.Enum):
    NONE = "none"
    FEATURE = "feature"
    SMART = "smart"


class FacilityType(str, enum.Enum):
    # Ascending capability. The planner's whole job is to stop sending people
    # up this ladder when a lower rung can discharge the obligation.
    SUBCENTRE = "subcentre"          # Ayushman Arogya Mandir / HWC
    PHC = "phc"                      # Primary Health Centre
    CHC = "chc"                      # Community Health Centre
    DISTRICT = "district_hospital"
    MOBILE_VAN = "mobile_van"        # comes to the village
    TELECONSULT = "teleconsult"      # comes down the phone line


class DebtStatus(str, enum.Enum):
    OPEN = "open"               # nobody has planned anything yet
    PLANNED = "planned"         # a care plan exists and outreach has gone out
    IN_PROGRESS = "in_progress"  # patient engaged, action under way
    CLOSED = "closed"           # evidence received, obligation discharged
    ESCALATED = "escalated"     # breached its clinical deadline
    UNREACHABLE = "unreachable"  # outreach exhausted, held open for review


class Flag(str, enum.Enum):
    NORMAL = "normal"
    ABNORMAL = "abnormal"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# People and places
# ---------------------------------------------------------------------------


class Person(BaseModel):
    """FHIR: Patient. All instances in demo mode are fictional."""

    id: str
    display_name: str
    age: int
    sex: Literal["male", "female", "other"]
    panchayat: str
    village: str
    language: str
    literacy: Literal["none", "basic", "functional"]
    phone_type: PhoneType
    phone_belongs_to_self: bool = True
    daily_wage_inr: float
    occupation: str
    caregiver_available: bool
    km_to_subcentre: float
    km_to_phc: float
    km_to_chc: float
    km_to_district: float
    comorbidities: list[str] = Field(default_factory=list)
    is_pregnant: bool = False
    prior_closures: int = 0
    # Synthetic stand-in for an ABHA (Ayushman Bharat Health Account) number.
    # Deliberately formatted so it can never collide with a real ABHA.
    pseudo_abha: str = ""

    def km_to(self, ftype: FacilityType) -> float:
        return {
            FacilityType.SUBCENTRE: self.km_to_subcentre,
            FacilityType.PHC: self.km_to_phc,
            FacilityType.CHC: self.km_to_chc,
            FacilityType.DISTRICT: self.km_to_district,
            FacilityType.MOBILE_VAN: 0.8,
            FacilityType.TELECONSULT: 0.0,
        }[ftype]


class Facility(BaseModel):
    """FHIR: Location + Organization."""

    id: str
    name: str
    type: FacilityType
    panchayat: str
    services: list[str] = Field(default_factory=list)
    # drug code -> units on hand
    stock: dict[str, int] = Field(default_factory=dict)
    # ISO date -> free appointment slots
    slots: dict[str, int] = Field(default_factory=dict)
    staff_present: bool = True


class OutreachWindow(BaseModel):
    """A mobile medical van or health camp visiting a panchayat on a date.

    This is the asset that makes zero-wage-loss care possible, and the asset
    that existing referral systems are blind to.
    """

    id: str
    kind: Literal["mobile_van", "health_camp", "asha_home_visit"]
    panchayat: str
    on_date: date
    capacity: int
    booked: int = 0
    services: list[str] = Field(default_factory=list)
    carries_stock: dict[str, int] = Field(default_factory=dict)

    @property
    def free(self) -> int:
        return max(0, self.capacity - self.booked)


class AshaWorker(BaseModel):
    """FHIR: Practitioner. The Accredited Social Health Activist."""

    id: str
    display_name: str
    panchayat: str
    villages: list[str]
    languages: list[str]
    open_tasks: int = 0
    # An ASHA is not an infinite resource. The planner respects this.
    weekly_visit_capacity: int = 25
    phone_type: PhoneType = PhoneType.SMART


# ---------------------------------------------------------------------------
# Clinical events and the debts they create
# ---------------------------------------------------------------------------


class ScreeningEvent(BaseModel):
    """FHIR: Observation. The moment the system learned something."""

    id: str
    person_id: str
    on_date: date
    kind: str                     # bp, blood_glucose, sputum_afb, haemoglobin, ...
    value: str
    flag: Flag
    facility_id: str
    source: Literal["aam_screening", "health_camp", "asha_visit", "opd", "self_report"]


class EvidenceItem(BaseModel):
    """Proof that care actually happened. No evidence, no closure."""

    kind: Literal[
        "bp_recorded",
        "glucose_recorded",
        "drug_dispensed",
        "test_result_received",
        "treatment_initiated",
        "specialist_note",
        "visit_logged",
        "immunisation_recorded",
    ]
    recorded_at: datetime
    recorded_by: str
    detail: str
    facility_id: str | None = None
    # Evidence asserted by a human without a system record is accepted but
    # flagged, and the ledger records the difference.
    corroborated: bool = True


class OutreachAttempt(BaseModel):
    channel: Literal["ivr_call", "whatsapp", "sms", "asha_visit", "loudspeaker"]
    attempted_at: datetime
    outcome: Literal["answered", "no_answer", "declined", "wrong_number", "delivered", "agreed"]
    language: str
    notes: str = ""


class CareDebt(BaseModel):
    """The core object. An obligation the health system owes one person."""

    id: str
    person_id: str
    condition: str                      # key into calibration.CLINICAL_DEADLINE_DAYS
    origin_event_id: str
    opened_on: date
    deadline_on: date
    required_action: Literal[
        "confirm_diagnosis",
        "initiate_treatment",
        "refill_medication",
        "followup_test",
        "specialist_review",
        "routine_visit",
    ]
    status: DebtStatus = DebtStatus.OPEN
    # Populated by the Triage agent.
    risk_score: float = 0.0
    risk_rationale: str = ""
    # Populated by the Reality agent.
    barriers: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    attempts: list[OutreachAttempt] = Field(default_factory=list)
    plan_id: str | None = None
    escalation_id: str | None = None

    def days_to_deadline(self, as_of: date) -> int:
        return (self.deadline_on - as_of).days

    def is_breached(self, as_of: date) -> bool:
        return self.days_to_deadline(as_of) < 0 and self.status not in {
            DebtStatus.CLOSED
        }


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class PlanStep(BaseModel):
    order: int
    actor: Literal["patient", "asha", "facility", "system", "doctor"]
    action: str
    where: str
    on_date: date | None = None
    facility_id: str | None = None
    outreach_window_id: str | None = None


class CostBreakdown(BaseModel):
    """What attending actually costs the patient, in rupees and in dignity.

    Existing referral systems implicitly price this at zero. That assumption
    is why 88% of Indian hypertensives are uncontrolled.
    """

    wage_loss_days: float
    wage_loss_inr: float
    fare_inr: float
    user_fee_inr: float
    total_inr: float
    travel_km: float
    # Cost as a share of one day's earnings. Above ~1.0 the patient is being
    # asked to choose between their blood pressure and their dinner.
    share_of_daily_wage: float


class CarePlan(BaseModel):
    id: str
    debt_id: str
    person_id: str
    strategy: str                 # short human label, e.g. "mobile van + ASHA escort"
    steps: list[PlanStep]
    cost: CostBreakdown
    days_to_closure: int
    predicted_no_show: float
    outreach_channel: Literal["ivr_call", "whatsapp", "sms", "asha_visit"]
    outreach_language: str
    asha_id: str | None = None
    rationale: str = ""
    # Guardrail: set when the deterministic safety core overrode the model.
    safety_overrides: list[str] = Field(default_factory=list)
    generated_by: Literal["llm", "deterministic"] = "deterministic"
    artifacts: dict[str, Any] = Field(default_factory=dict)
    # The honest comparison: what a conventional referral/reminder system
    # would have told this person to do.
    counterfactual: dict[str, Any] = Field(default_factory=dict)


class Escalation(BaseModel):
    id: str
    debt_ids: list[str]
    raised_on: date
    to_role: str                 # e.g. "Block Medical Officer"
    panchayat: str | None = None
    headline: str
    brief_markdown: str
    systemic_cause: str = ""
    generated_by: Literal["llm", "deterministic"] = "deterministic"


# ---------------------------------------------------------------------------
# Agent trace — what the dashboard shows while the agents are working
# ---------------------------------------------------------------------------


class AgentStep(BaseModel):
    agent: str
    phase: str
    started_at: datetime
    duration_ms: int
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    used_llm: bool = False
    tokens: int | None = None


class AgentRun(BaseModel):
    id: str
    debt_id: str
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    plan: CarePlan | None = None
    error: str | None = None
