# Architecture

## The one idea

A **care debt** is an obligation the health system owes a named person,
created the moment an abnormal result exists and closable only by evidence
that care actually happened.

Everything else follows from taking that object seriously. Once an unclosed
abnormal result is a first-class record with a clinical deadline rather than a
row in a screening report, you can rank it, price it, route it, escalate it,
and count it — none of which you can do to a PDF.

## Why a fixed pipeline, not an agent loop

```
Triage ──▶ Reality ──▶ Supply ──▶ Planner ──▶ Verifier
  │           │           │          │           │
  │           │           │          │           └─ deterministic only
  │           │           │          └───────────── optimiser + bounded model
  │           │           └──────────────────────── no model at all
  │           └──────────────────────────────────── deterministic + narrative
  └──────────────────────────────────────────────── formula + bounded model
```

A single model improvising across all five stages would be more impressive to
watch and considerably worse at the job, because each stage has a *different*
correctness requirement:

- **Supply must never hallucinate.** It reports what venues exist, what they
  can do, what is in stock and what slots are free. A fabricated appointment
  sends a sick person on a bus for nothing. So no model touches it.
- **Triage must never re-order a critical case.** The model can contribute
  clinical gestalt a formula misses — household transmission risk, pregnancy
  interacting with a condition — but within a hard ±12 band, and a negative
  adjustment on a critical condition is refused outright.
- **Verifier must be reproducible.** Whether an obligation is discharged is
  not a judgement call, and an auditor must be able to re-derive it.
- **Planner genuinely benefits from judgement**, but only after the
  arithmetic has produced a safe shortlist.

So the orchestration is explicit and the ordering is auditable. The model is
invoked at the three points where judgement beats rules: weighing messy
barriers into prose, choosing among a pre-vetted shortlist, and writing for a
human reader.

Every intervention the guardrails make is recorded on the plan as a
`safety_override` and surfaced in the dashboard. A guardrail that fires
silently is a guardrail nobody will trust.

## The quantitative spine

`behaviour.py` is where the project earns its keep.

**Cost.** What attending actually costs a household: lost wages (priced at
the household casual wage even when the patient has no cash income, because
costing unpaid labour at zero is how women's follow-up gets deprioritised),
bus fare doubled where an escort is needed, and the informal charges that are
not supposed to exist.

**Attendance.** A logistic model over named, actionable barriers:

```
logit(no-show) = β₀
  + β_cost   · (out-of-pocket cost / daily wage)
  + β_dist   · log(1 + round-trip km)
  + β_wait   · (days until slot / 7)
  + β_wage   · working days lost
  + β_lang   · outreach not in the patient's language
  + β_text   · text-only outreach to a low-literacy user
  + β_stock  · medicine expected to be unavailable
  + β_female · woman with no caregiver available
  − β_asha   · ASHA accompanies the patient
  − β_prior  · previous successful closures (capped at 3)
```

Every term is something a health worker can point at and act on. That is the
design constraint: once attendance is a *predicted quantity* decomposed into
*removable obstacles*, routing becomes an optimisation problem instead of a
motivational one.

## The objective function

`planner.py` minimises:

```
expected_harm    = P(no-show) × severity in healthy life-years
patient_burden   = 0.6 × (cost to patient / daily wage)
system_cost      = scarcity of the venue  (+ 0.30 if an ASHA escort is used)
deadline_penalty = 25.0 if the option misses the clinical deadline
```

`system_cost` is the term nobody else prices. A district-hospital specialist
slot is scored twenty times a mobile-van visit, because those slots are the
scarcest resource in a block and the people who need them most are the ones
who lose when they are spent on a blood-pressure recheck.

Three constraints are hard, enforced in code rather than in a prompt:

1. A medication refill is never routed to a venue expected to be out of stock.
2. A venue must genuinely be able to perform the required action. Starting TB
   treatment needs programme registration, so `mo_consult` is explicitly *not*
   accepted for it; a specialist examination cannot be done by van or phone.
3. A plan that misses the clinical deadline loses to one that does not,
   however much cheaper it looks.

## Honesty mechanisms

These are deliberate design features, not incidental:

- **The counterfactual is not a straw man.** It is a referral to the
  highest-capability facility for the condition, on that facility's next free
  slot, notified by SMS — what a correctly operating referral system does
  today. Each of those three choices is defensible alone; together they
  produce a no-show.
- **Barriers we have not removed stay counted.** We have outreach copy in
  Hindi and Bhojpuri only, so a Santali speaker's plan keeps the
  language penalty in its attendance prediction and the artefact is flagged
  `fell_back_to_hindi`.
- **The channel must match the person.** A household with no handset gets a
  human at the door. If no ASHA has capacity, the plan is marked
  undeliverable and escalated rather than counted as outreach.
- **Predictions are logged before outcomes.** Both `plan_created` and
  `debt_closed` go to the ledger.
- **The status-quo cascade is frozen.** It describes what the block achieved
  without Nirantar, so it cannot drift upward while you watch.
- **Escalations blame systems, never patients.** "Non-compliant patient" is
  not a category anywhere in this codebase. If someone cannot attend, the
  plan was wrong.

## Scale

Capacity is shared mutable state — one patient booking the Thursday van slot
must mean the next patient sees it gone — so `plan_batch` draws down the same
world in bounded chunks rather than racing.

Measured: **300 care obligations planned in 0.15 s, zero model calls.** That
is the production path for volume work. The model is reserved for artefacts a
human reads. A block of 200,000 people cannot afford a model call per
follow-up and this design does not need one.

## Storage

SQLite behind a small locked `Db` wrapper. FastAPI runs sync endpoints in a
thread pool, so concurrent requests touch one connection; a `sqlite3`
connection tolerates that only if a statement and its fetch are not
interleaved. When they interleaved here the symptom was not a clean error — it
was `SELECT COUNT(*)` returning `None` and crashing the public ledger
endpoint while a batch ran.

Ledger appends additionally hold the lock across *read-head-then-insert*,
because that read decides the sequence number and previous hash the insert
commits to. Without it, two concurrent writers pick the same sequence number
and chain to the same predecessor — a forked chain, which is precisely the
failure the hash chain exists to make impossible. Both are regression-tested.

The `Db` interface is deliberately narrow so Postgres is a drop-in change for
anything beyond a single block.

## FHIR mapping

| Nirantar | FHIR R4 |
|---|---|
| `Person` | `Patient` |
| `ScreeningEvent` | `Observation` |
| `Facility` | `Location` + `Organization` |
| `AshaWorker` | `Practitioner` |
| `CareDebt` | `Task` (with `focus` → the `Observation`) |
| `CarePlan` | `CarePlan` |
| `EvidenceItem` | `Observation` / `MedicationDispense` |

Care debts derive from `Observation` resources that **already exist** in the
NCD portal. Nirantar needs no new data collection; the abnormal results are
already sitting there.
