# Against the judging rubric

Four criteria, 25% each. This document answers each one directly and points
at the code or endpoint that backs the claim, including where the honest
answer is "not yet".

---

## 1. Size of the problem — 25%

*How many citizens face it.*

Population-based screening at Ayushman Arogya Mandirs has reached **tens of
crores** of Indians for hypertension, diabetes, and oral, cervical and breast
cancer. The screening is genuinely world-class at scale.

The follow-up is not. Cascade analyses put **hypertension control at roughly
one in eight** affected Indian adults, with the losses concentrated at
referral and treatment initiation rather than at screening or at drug
availability. Add the TB programme's initial loss to follow-up — people
diagnosed and never started on treatment — and the ~42% of mothers who do not
complete four antenatal visits, and the affected population is in the **tens
of crores**, not the lakhs.

Crucially this is not a diagnostic-access problem or a drug-cost problem.
Amlodipine costs rupees and the screening already happened. The loss is
*entirely* in the handoff, which means it is addressable by software in a way
that most health problems of this size are not.

In the modelled block: **11.4% of the entire population is owed care right
now** — 2,727 of 24,000 people. Scale that share and it is a national
backlog in the crores.

> Endpoint: `/api/overview`, `/api/cascade`, `/api/conditions`

## 2. Severity of the problem — 25%

*The human suffering or economic loss it causes.*

Each open obligation is weighted by expected healthy life-years lost if never
discharged, informed by Global Burden of Disease disability weights. The
modelled block alone carries **~8,167 healthy life-years at stake**.

The severity is not evenly spread, which is why ranking matters: a confirmed
TB case never started on treatment carries 9.0 healthy years and is
transmissible to the household; an overdue blood-pressure recheck carries 3.0.
Forty of the former outrank four hundred of the latter, and a count-ordered
worklist — which is what a due-date queue produces — gets that exactly
backwards.

The economic severity compounds it. Out-of-pocket spending is about **47% of
all Indian health expenditure**. Pursuing every open obligation in the
modelled block through conventional referral would load roughly **₹10.8 lakh
of out-of-pocket cost** onto some of the poorest households in the country —
in one block. Nobody currently measures this, which is why nobody optimises
it, and why it keeps being spent badly.

> Endpoint: `/api/barriers`, `/api/aging`, `/api/escalations/clusters`

## 3. Quality of the solution — 25%

*Design craft plus real effectiveness.*

**The insight.** Reminder systems fail because they price a follow-up visit at
zero. Nirantar prices it honestly — lost wages, fares, informal charges, days
gone — then predicts attendance as a function of that price and routes around
the binding constraint. See [ARCHITECTURE.md](ARCHITECTURE.md).

**Genuinely agentic, not a chatbot.** Five agents with different authority
levels and an explicit objective function. The model is bounded at every point
where it could cause harm, and every guardrail intervention is recorded and
displayed rather than hidden.

**It runs where the billion actually is.** Voice-first in the patient's own
language because a quarter of adults in the modelled block cannot read an SMS;
a human at the door for households with no handset; scripts that never name
the diagnosis because handsets are shared; ASHA task cards sized for a feature
phone.

**Engineering quality.** 70 tests, mostly adversarial. The suite asserts a
mobile van can never initiate TB treatment, a refill is never sent to an empty
shelf, a patient with no phone is never promised a WhatsApp message, wrong-typed
and backdated evidence cannot close an obligation, tampering with or forging a
ledger row breaks verification, concurrent writers cannot fork the hash chain,
and the process refuses to start if pointed at real records without an identity
provider.

Two of those tests exist to keep the *project* honest rather than the code:
one fails the build if the simulated cascade stops reproducing India's actual
follow-up gap; another fails if any constant lacks a source or an explained
assumption.

**Digital public good, properly.** Apache-2.0. FHIR R4-shaped so an
ABDM-compliant state system is an adapter, not a migration. Derives from
`Observation` records that already exist, so adoption needs no new data
collection.

> See: `backend/nirantar/agents/`, `backend/tests/`, `/api/calibration`

## 4. Proven impact — 25%

*Actual deployment data, not intentions.*

This is the criterion most projects fudge, so measurement is built in as a
feature rather than reported as a claim.

**The Impact Ledger** is a hash-chained, Ed25519-signed, append-only log of
every state change. Fetch it, recompute the hashes, verify the signatures
against the published public key. You do not have to trust us.

- Nothing closes without **evidence** — a BP value, a dispensing record, a
  test result. There is no API through which an obligation can be marked
  closed without an evidence payload.
- **Predictions are logged before outcomes are known.** Both `plan_created`
  and `debt_closed` are recorded, so we cannot log only our successes.
- Resetting the demo world does not touch the ledger.
- The chain is public; the patients are not.

> Endpoints: `/api/ledger/verify`, `/api/ledger/entries`,
> `/api/ledger/public-key`, `/api/ledger/summary`

### What we can honestly claim today

Measured in the demo, derived from the signed chain:

| Measure | Result |
|---|---|
| Obligations planned, deterministic optimiser | 300 in **0.15 s**, zero model calls |
| Household cost avoided vs conventional referral | **~₹84,000** across those 300 |
| Patient travel removed | **~6,275 km** |
| Plans needing **no travel at all** | **183 of 300** |
| Expected additional attendances | **~119**, from summed no-show reduction |

On the single worked case in the README: ₹747 → ₹420, and predicted
attendance 42% → 87%.

### What we cannot claim, and will not

**These are modelled predictions, not realised outcomes.** Every rupee figure
is the cost model's estimate against a counterfactual referral, recorded
before any outcome was known. They are honest predictions from a published,
auditable model. They are **not** evidence of money actually saved, because
this has not yet run in a real block.

The attendance model's coefficients are **assumptions**, chosen so the
aggregate cascade reproduces published completion rates, not fitted to a
patient-level dataset. They are listed as assumptions at `/api/calibration`
and in the dashboard. A real deployment would refit them on its own data
inside a month, and the code is structured so that is a configuration change.

The district is simulated. No real person's data is in this system.

See [DATA_SOURCES.md § Limits of this work](DATA_SOURCES.md#limits-of-this-work)
for the full list, which is also rendered in the dashboard's *Method &
sources* tab — because a model whose assumptions you cannot inspect is not
evidence of anything, and a project that hides them has already failed this
criterion.

---

## Sponsor awards

**Best xSpan CareHub integration.** Care debts derive from `Observation`
resources and close against `MedicationDispense`/`Observation` evidence —
exactly the care-coordination shape CareHub's Digital Twin APIs expose. The
adapter boundary is `backend/nirantar/data/generator.py`: replace the
generator with a CareHub client and the five agents are unchanged.

**Best use of AgentFoundry agents.** Five agents with distinct, documented
authority levels, bounded model intervention, recorded guardrail overrides,
and a live streaming trace so the reasoning is inspectable rather than
asserted.
