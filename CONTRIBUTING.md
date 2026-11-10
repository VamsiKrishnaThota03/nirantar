# Contributing

Nirantar is a digital public good. The most valuable contributions are not
features.

## What this project needs most

**Native-speaker outreach copy.** The single highest-value contribution. We
have hand-written copy in Hindi and Bhojpuri only. Every other language falls
back to Hindi, is flagged, and *keeps its penalty in the attendance model* —
so adding a language measurably improves predicted outcomes rather than just
adding a string. Add it to `backend/nirantar/ivr/scripts.py` (`REASON_PHRASE`)
and `translit.py`. Required: you are a native or fluent speaker, the phrasing
is non-diagnostic (see below), and an English gloss accompanies every line.

**Arguing with the attendance model.** The coefficients in
`calibration.py` marked `ASSUMED` are modelling choices, not measurements. If
you have published evidence or field data that contradicts them, open an issue
with the source. This is the most useful kind of criticism this project can
receive.

**Field reality checks.** If you have worked as an ASHA, an ANM, a Medical
Officer or a Block Medical Officer and something here is wrong about how the
system actually behaves, please say so. Code is easy to change; a wrong mental
model is not.

**A real health-record adapter.** `backend/nirantar/data/generator.py` is the
seam. A working ABDM/FHIR client behind the same `World` interface would make
this deployable.

## Non-negotiables

These are not style preferences. A pull request that breaks one will be
declined with an explanation.

1. **No clinical decision is made by a language model alone.** Every agent
   keeps a complete deterministic core. The model advises within hard bounds,
   and every bound it hits is recorded as a `safety_override` and shown in the
   interface. A guardrail that fires silently is one nobody will trust.

2. **Nothing closes without evidence.** Do not add a `status = "done"` path,
   a bulk-close endpoint, or a field that lets outreach count as an outcome.
   The absence of that API is the feature.

3. **Outreach never names the diagnosis.** Handsets are shared and often
   belong to a husband or son rather than to the woman being called. A script
   says a check-up follow-up is pending; it does not announce that someone may
   have tuberculosis.

4. **No barrier may be claimed as removed unless it was removed.** If we have
   no copy in a patient's language, the language penalty stays in the
   prediction. If the household has no phone, the channel is a person at the
   door. Inflating a prediction is worse than a low one.

5. **Escalations are raised against systems, never patients.**
   "Non-compliant patient" is not a category in this codebase. If someone
   cannot attend, the plan was wrong.

6. **Loopback defaults, and the gate stays closed.** `HOST` defaults to
   `127.0.0.1`. A missing configuration must never become an open door. See
   [`SECURITY.md`](SECURITY.md).

7. **Every constant carries its provenance.** A real source, or an explained
   assumption. There is a test for this.

## Working on it

```bash
make setup
make test        # 70 backend tests + frontend typecheck
make build
make backend
```

Tests are adversarial by preference. A test that asserts the system *refuses*
to do something harmful is worth more than one asserting the happy path works.
If you fix a bug, add the test that would have caught it — the concurrency and
outreach-channel tests in this repo both exist because the bug shipped first.

Python is formatted to 88 columns with type hints throughout; TypeScript is
strict with `noUnusedLocals`. Charts follow the rules in
`frontend/src/components/charts.tsx` — one hue per series, a legend for two or
more series, a table view for every chart, and a hover target bigger than the
mark.

## Licence

Contributions are accepted under Apache-2.0. By opening a pull request you
agree your contribution may be released under that licence to the Code for
India GitHub organisation, so any NGO or government body can adopt it. You
retain attribution as a contributor.
