"""Calibration constants drawn from published Indian public-health sources.

Every record Nirantar serves in demo mode is FICTIONAL. No real person's
data is present, and none was used. What the published figures do is set the
*shape* of the generated district — prevalence, follow-up completion, wage
levels, travel distances — so the demo behaves like a real block rather than
like a toy.

Each constant carries its source. Figures are rounded and some are national
rather than district-level, so treat them as an illustrative calibration, not
as an epidemiological estimate for any specific place. Where a published
number did not exist for a parameter the model needs (for example the exact
weight of travel cost on no-show behaviour), the value is marked ASSUMED and
is a modelling choice we expose rather than hide — see docs/DATA_SOURCES.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Calibrated:
    value: float
    source: str
    note: str = ""


# ---------------------------------------------------------------------------
# Disease burden among adults. NFHS-5 measured blood pressure and random
# blood glucose for all adult respondents, which is why it is the anchor for
# screening-stage prevalence rather than treated-case registries.
# ---------------------------------------------------------------------------

HTN_PREVALENCE_MEN = Calibrated(
    0.24, "NFHS-5 (2019-21), National Report, hypertension among men 15+"
)
HTN_PREVALENCE_WOMEN = Calibrated(
    0.21, "NFHS-5 (2019-21), National Report, hypertension among women 15+"
)
HIGH_BLOOD_GLUCOSE_MEN = Calibrated(
    0.16, "NFHS-5 (2019-21), random blood glucose >140 mg/dl or on medication, men 15+"
)
HIGH_BLOOD_GLUCOSE_WOMEN = Calibrated(
    0.14, "NFHS-5 (2019-21), random blood glucose >140 mg/dl or on medication, women 15+"
)
ANAEMIA_PREGNANT_WOMEN = Calibrated(
    0.52, "NFHS-5 (2019-21), anaemia among pregnant women 15-49"
)
ANAEMIA_WOMEN_ALL = Calibrated(0.57, "NFHS-5 (2019-21), anaemia among women 15-49")

# ---------------------------------------------------------------------------
# The gap Nirantar exists to close. These are the numbers that make the case:
# India finds the problem and then loses the patient.
# ---------------------------------------------------------------------------

NCD_SCREENINGS_CUMULATIVE_CRORE = Calibrated(
    40.0,
    "Ministry of Health & Family Welfare / NP-NCD reporting on cumulative "
    "population-based screening at Ayushman Arogya Mandirs (Health & Wellness "
    "Centres)",
    "Order-of-magnitude figure; MoHFW reports cumulative screening counts in "
    "the tens of crores across hypertension, diabetes and three cancers.",
)
HTN_TREATMENT_CASCADE_CONTROLLED = Calibrated(
    0.12,
    "ICMR-INDIAB and India Hypertension Control Initiative cascade analyses",
    "Roughly one in eight Indian adults with hypertension has it controlled; "
    "the losses are concentrated at referral and treatment initiation, not at "
    "screening.",
)
TB_NOTIFIED_LAKH_PER_YEAR = Calibrated(
    24.0, "India TB Report 2023 (Central TB Division), annual notifications"
)
TB_INITIAL_LOSS_TO_FOLLOWUP = Calibrated(
    0.07,
    "India TB Report / NIKSHAY programme analyses of initial loss to follow-up",
    "Diagnosed but never started on treatment. Each one is an open care debt "
    "with a two-week clinical deadline.",
)
ANC_FOUR_PLUS_VISITS = Calibrated(
    0.58, "NFHS-5 (2019-21), mothers with 4+ antenatal care visits"
)
FULL_IMMUNISATION_12_23M = Calibrated(
    0.76, "NFHS-5 (2019-21), children 12-23 months fully immunised"
)

# ---------------------------------------------------------------------------
# Economics of attending a follow-up. This is the half of the problem that
# reminder systems ignore entirely.
# ---------------------------------------------------------------------------

RURAL_CASUAL_DAILY_WAGE_INR = Calibrated(
    400.0,
    "Labour Bureau Wage Rates in Rural India / RBI Handbook of Statistics on "
    "the Indian Economy, average daily wage for rural casual labour",
    "A full day lost to a district-hospital trip costs about this much, "
    "before fares. It is the single biggest reason a referral is ignored.",
)
OOP_SHARE_OF_HEALTH_SPEND = Calibrated(
    0.47,
    "National Health Accounts Estimates for India, out-of-pocket share of "
    "total health expenditure",
)
BUS_FARE_INR_PER_KM = Calibrated(
    1.1,
    "State road transport corporation ordinary-service fare tables",
    "ASSUMED blended rate across states for a rural ordinary bus service.",
)

# ---------------------------------------------------------------------------
# No-show model coefficients. A logistic model over the barriers above.
#
# These are ASSUMED weights, not fitted to a published dataset. They are
# chosen so that the model, run across the generated district, reproduces the
# aggregate completion rates published above (see tests/test_calibration.py,
# which fails the build if the simulated cascade drifts away from the
# published anchors). That is the honest claim: the *aggregate behaviour* is
# anchored to real statistics; the individual-level weights are a transparent
# modelling choice, published here so anyone can argue with them.
# ---------------------------------------------------------------------------

NOSHOW_INTERCEPT = Calibrated(
    -3.00,
    "ASSUMED",
    "Baseline log-odds of not attending for someone facing none of the "
    "modelled barriers. Implies about a 5% no-show floor, which is roughly "
    "what village immunisation outreach days achieve.",
)
NOSHOW_W_COST_WAGE_RATIO = Calibrated(
    1.30, "ASSUMED", "Per unit of (out-of-pocket cost / daily wage)."
)
NOSHOW_W_LOG_DISTANCE = Calibrated(
    0.18,
    "ASSUMED",
    "Per log(1 + round-trip km). Kept small because most of the effect of "
    "distance already arrives through fares and lost working days; a larger "
    "weight double-counts it.",
)
NOSHOW_W_WAIT_WEEKS = Calibrated(0.26, "ASSUMED", "Per week until the offered slot.")
NOSHOW_W_WAGE_LOSS_DAYS = Calibrated(0.55, "ASSUMED", "Per full working day lost.")
NOSHOW_W_ASHA_ACCOMPANIED = Calibrated(
    -0.95, "ASSUMED", "Accredited Social Health Activist accompanies the patient."
)
NOSHOW_W_LANGUAGE_MISMATCH = Calibrated(
    0.45, "ASSUMED", "Outreach language is not the patient's own."
)
NOSHOW_W_NO_CAREGIVER_FEMALE = Calibrated(
    0.40,
    "ASSUMED",
    "Woman with no available caregiver; mobility constraint widely documented "
    "in qualitative access literature.",
)
NOSHOW_W_EXPECTED_STOCKOUT = Calibrated(
    0.70,
    "ASSUMED",
    "Patient expects the drug to be unavailable. A wasted trip teaches people "
    "not to make the next one.",
)
NOSHOW_W_PRIOR_CLOSURE = Calibrated(
    -0.30, "ASSUMED", "Per prior successfully closed care debt, capped."
)
NOSHOW_W_FEATURE_PHONE_TEXT = Calibrated(
    0.35,
    "ASSUMED",
    "Text-only outreach to a patient with low literacy or no smartphone.",
)

# Clinical deadlines, in days, from the moment an abnormal result exists to
# the moment action stops being timely. Sourced from programme operational
# guidelines rather than invented.
CLINICAL_DEADLINE_DAYS: dict[str, int] = {
    "tb_pulmonary_suspect": 14,
    "tb_confirmed_not_initiated": 7,
    "hypertension_suspect": 30,
    "hypertension_refill_due": 7,
    "diabetes_suspect": 30,
    "diabetes_refill_due": 7,
    "anaemia_pregnancy_severe": 7,
    "anaemia_pregnancy_moderate": 21,
    "anc_visit_overdue": 14,
    "oral_cancer_suspect": 21,
    "cervical_cancer_suspect": 30,
    "breast_lump_suspect": 21,
    "immunisation_overdue": 30,
    "child_sam_suspect": 7,
}

# Severity weight per condition: expected years of healthy life lost if the
# debt is never closed, used for risk ranking. Order-of-magnitude values
# informed by Global Burden of Disease disability weights; ASSUMED precision.
SEVERITY_DALY_WEIGHT: dict[str, float] = {
    "tb_confirmed_not_initiated": 9.0,
    "tb_pulmonary_suspect": 7.5,
    "child_sam_suspect": 8.0,
    "anaemia_pregnancy_severe": 6.0,
    "oral_cancer_suspect": 5.5,
    "breast_lump_suspect": 5.0,
    "cervical_cancer_suspect": 4.8,
    "anc_visit_overdue": 3.5,
    "hypertension_suspect": 3.0,
    "diabetes_suspect": 2.8,
    "hypertension_refill_due": 2.2,
    "diabetes_refill_due": 2.0,
    "anaemia_pregnancy_moderate": 1.6,
    "immunisation_overdue": 1.4,
}

HUMAN_LABEL: dict[str, str] = {
    "tb_confirmed_not_initiated": "TB confirmed, treatment not started",
    "tb_pulmonary_suspect": "Presumptive TB, needs confirmatory test",
    "child_sam_suspect": "Child with severe acute malnutrition",
    "anaemia_pregnancy_severe": "Severe anaemia in pregnancy",
    "anaemia_pregnancy_moderate": "Moderate anaemia in pregnancy",
    "oral_cancer_suspect": "Suspicious oral lesion",
    "breast_lump_suspect": "Breast lump, needs examination",
    "cervical_cancer_suspect": "Abnormal cervical screening",
    "anc_visit_overdue": "Antenatal visit overdue",
    "hypertension_suspect": "Raised blood pressure, unconfirmed",
    "diabetes_suspect": "Raised blood glucose, unconfirmed",
    "hypertension_refill_due": "Blood-pressure medication refill overdue",
    "diabetes_refill_due": "Diabetes medication refill overdue",
    "immunisation_overdue": "Childhood immunisation overdue",
}


def all_sources() -> list[dict[str, str]]:
    """Every calibrated constant with its provenance, served over the API.

    The dashboard links to this so a judge can audit where each number came
    from without reading the source tree.
    """
    out: list[dict[str, str]] = []
    for name, obj in sorted(globals().items()):
        if isinstance(obj, Calibrated):
            out.append(
                {
                    "constant": name,
                    "value": str(obj.value),
                    "source": obj.source,
                    "note": obj.note,
                    "assumed": "yes" if obj.source == "ASSUMED" else "no",
                }
            )
    return out
