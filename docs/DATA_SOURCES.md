# Data sources, calibration, and limits

**Every record this system serves in demo mode is fictional. No real
person's data was used and none is present.** Bharatpur block and Saryupar
district are invented, as are all names and villages.

What is real is the *shape*. Published Indian statistics set prevalence,
follow-up completion, wage levels and travel distances, so the generated
block behaves like a real block of its size rather than like a toy. The live,
machine-readable version of this list is at `/api/calibration`, and the
dashboard renders it under *Method & sources*.

## Published sources

| Parameter | Value | Source |
|---|---|---|
| Hypertension, men 15+ | 24% | NFHS-5 (2019–21), National Report |
| Hypertension, women 15+ | 21% | NFHS-5 (2019–21) |
| High blood glucose, men 15+ | 16% | NFHS-5 — random glucose >140 mg/dl or on medication |
| High blood glucose, women 15+ | 14% | NFHS-5 |
| Anaemia, pregnant women 15–49 | 52% | NFHS-5 |
| Anaemia, all women 15–49 | 57% | NFHS-5 |
| 4+ antenatal visits | 58% | NFHS-5 |
| Full immunisation, 12–23 months | 76% | NFHS-5 |
| TB notifications per year | ~24 lakh | India TB Report 2023, Central TB Division |
| TB initial loss to follow-up | ~7% | India TB Report / NIKSHAY analyses |
| Hypertension control achieved | ~12% | ICMR-INDIAB and India Hypertension Control Initiative cascade analyses |
| Cumulative NCD screenings | tens of crores | MoHFW / NP-NCD reporting on population-based screening at Ayushman Arogya Mandirs |
| Rural casual daily wage | ~₹400 | Labour Bureau *Wage Rates in Rural India* / RBI Handbook of Statistics |
| Out-of-pocket share of health spend | ~47% | National Health Accounts Estimates for India |

Figures are rounded, and some are national rather than district-level. Treat
them as an illustrative calibration, not as an epidemiological estimate for
any specific place.

Clinical deadlines (days from an abnormal result existing to action ceasing to
be timely) are drawn from programme operational guidelines. Severity weights
(expected healthy life-years lost if never discharged) are informed by Global
Burden of Disease disability weights; their precision is assumed.

## Assumptions

No published Indian dataset gave us the weights of an individual-level
attendance model, so they are **modelling choices**, published here rather
than buried. These are the numbers worth arguing with.

| Parameter | Value | Note |
|---|---|---|
| Intercept | −3.00 | Implies a ~5% no-show floor for someone facing none of the modelled barriers, which is roughly what village immunisation outreach days achieve |
| Cost / daily-wage ratio | +1.30 | Per unit of (out-of-pocket cost ÷ daily wage) |
| log(1 + round-trip km) | +0.18 | Kept small deliberately: most of distance's effect already arrives through fares and lost days, and a larger weight double-counts it |
| Weeks until slot | +0.26 | Per week |
| Working days lost | +0.55 | Per full day |
| ASHA accompanies | −0.95 | The largest modifiable protective factor in the model |
| Outreach not in patient's language | +0.45 | |
| Woman with no caregiver | +0.40 | Mobility constraint, widely documented in access literature |
| Medicine expected unavailable | +0.70 | A wasted trip teaches people not to make the next one |
| Text-only to low-literacy user | +0.35 | |
| Prior successful closures | −0.30 each, capped at 3 | Trust compounds |
| Bus fare | ₹1.1/km | Blended rate across state road transport ordinary services |

### How these are kept honest

The claim is narrow and testable: **the aggregate behaviour is anchored to
published statistics; the individual weights are a transparent choice.**

`backend/tests/test_calibration.py` fails the build if the simulated world
drifts from its anchors — screening coverage, hypertension detection rate, TB
initiation rate, backlog age, and the plausibility band on mean predicted
no-show. One test exists specifically to protect the project's central
empirical claim: `test_ncd_follow_up_is_far_worse_than_tb` asserts that TB
closure exceeds hypertension closure by a wide margin, because India closes TB
obligations far more often than NCD ones — one has an active chase mechanism,
the other has a screening camp and a hope. If that inequality ever inverts in
the model, the model has stopped describing India.

Another test asserts every constant carries either a real source or an
explained assumption. A magic number nobody can argue with is not a model.

The mean predicted no-show under conventional referral lands around **51%**.
Published NCD referral-completion figures imply something closer to 60–70%,
so **the model under-states the problem rather than over-stating it.** That
direction was chosen on purpose.

## Limits of this work

Stated plainly, and rendered in the dashboard so a judge sees them without
reading this file.

**The district is simulated.** Calibrated to published national statistics is
not the same as validated against a real block's records.

**The attendance model is not fitted.** Its weights are the assumptions above,
chosen so the aggregate cascade reproduces published completion rates. A real
deployment would refit them on its own data within a month.

**Savings are modelled, not measured.** Every rupee figure is a prediction
from the cost model against a counterfactual referral, logged before any
outcome was known. Honest predictions — not evidence of realised savings. The
ledger is deliberately designed so that distinction stays visible.

**The vernacular copy needs native review.** Only Hindi and Bhojpuri have
hand-written copy. Every generated script is flagged
`requires_native_review`, and a language we lack copy for keeps its penalty in
the attendance model rather than being quietly counted as handled.

**No real telephony or health-record integration.** The outreach artefacts are
generated and inspectable but not dialled. The data model is FHIR R4-shaped so
an ABDM-compliant system is an adapter rather than a migration, but that
adapter is not written.

**The severity weights are coarse.** Expected healthy life-years per condition
are order-of-magnitude values. They are good enough to establish that
confirmed TB outranks a BP recheck, which is the decision the ranking actually
has to make; they are not good enough for a cost-effectiveness submission.

**SQLite and an in-process rate limiter** suit one block, not a state. Both
are called out in [`../SECURITY.md`](../SECURITY.md) with their replacements.

**The trial is a simulation, not a field trial.** It is built to be able to
fail — outcomes are drawn from a ground truth deliberately perturbed away from
the planner's beliefs, the status-quo arm's plausibility is asserted by a
test, and the results are reported as a distribution across worlds. All of
that makes it a *stronger* piece of evidence than a single run of our own
model against itself. It is still not evidence about any real block. The
honest reading is: "optimising against an imperfect behavioural model helped
in every simulated world we tried, including ones where the model was
materially wrong." Not: "this saves ₹X in Bharatpur."

**The trial's ground-truth model shares the planner's functional form.** Only
the coefficients differ. We are not claiming to know a better *shape* for
human attendance behaviour, and if the true shape is different — a threshold
effect rather than a smooth logistic, say — the trial would not detect it.
That is a real limitation of this design and the most likely way these results
are optimistic.

**The equity audit measures service rates, not health outcomes.** "Served"
means an obligation was discharged with evidence. It does not measure whether
the care was good, or whether the person's blood pressure actually came
down.
