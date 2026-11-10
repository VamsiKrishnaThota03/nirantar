# Demo script — 3 minutes

The submission asks for a 2–3 minute walkthrough. This is the running order,
timed, with what to say. Everything below is live in the app; nothing is
staged.

Open on **The gap** tab, light or dark, your preference.

---

## 0:00 — The claim (20s)

> "India screens superbly and follows up terribly. Tens of crores of people
> have been screened for hypertension, diabetes and three cancers. Roughly one
> in eight Indian adults with hypertension actually has it controlled. The
> diagnosis was right and the medicine costs rupees — what's missing is the
> step between *we found your problem* and *we treated your problem*. That's
> not a clinical problem. It's a logistics problem."

Point at the headline tiles: **2,727 people owed care right now — 11% of this
block.**

## 0:20 — Why reminders don't fix it (30s)

Scroll to **What a follow-up actually costs**.

> "Here's why reminder apps don't work. The average follow-up in this block
> costs the household ₹367 and a 22 km round trip. That's a day's wages. Half
> of these people are predicted not to attend — and the top barrier isn't
> motivation, it's that the system doesn't speak their language, they live 25
> km from the hospital, and the trip costs more than they earn in a day."

> "Existing referral software prices that visit at zero rupees and then
> records non-attendance as the patient's fault."

Then the schematic:

> "And the two panchayats furthest from the district hospital are exactly the
> two the mobile medical units never reach."

## 0:50 — Watch the agents (70s)

Go to **Watch the agents**. Top of the worklist. Click **Run the agents**.

> "This is the worklist ordered by expected harm, not by date. Top of the
> queue: a 25-year-old man, confirmed TB, treatment never started, 75 days
> past the clinical deadline. No phone in the household. Speaks Santali."

As the trace fills:

> "Five agents. Triage ranks by harm. Reality prices what a conventional
> referral would cost him — ₹747 and a 58% chance he doesn't go. Supply looks
> up what can actually treat him, with the drug in stock. Planner optimises.
> Verifier sets the evidence bar. Sub-millisecond, no model calls needed."

Then the counterfactual:

> "₹747 down to ₹420. 58% no-show down to 13%. ₹327 back in the household and
> he's roughly twice as likely to start treatment."

**Now the three details that matter** — this is the part that wins it:

> "Three things it did that I want to point out.
>
> One: it refused to send him to the mobile van, which was cheaper and
> closer. Starting TB treatment means registering him on the national
> programme. A van can't do that. Cheap only wins where the care is
> equivalent.
>
> Two: he speaks Santali and we only have outreach copy in Hindi and
> Bhojpuri. So it flags that, and it *keeps the language penalty in the
> prediction*. That's why it says 13% and not 8%. We don't get credit for a
> barrier we didn't remove.
>
> Three: he has no phone. So outreach isn't a call or an SMS — it's an ASHA
> walking to his house. And if no ASHA had capacity this week, the plan would
> be flagged undeliverable and escalated, not counted as outreach."

## 2:00 — Proven impact (45s)

Go to **Impact ledger**. Click **Plan 300 obligations now**.

> "Judging asks for proven impact, not intentions. So measurement is a
> feature, not a slide."

> "300 obligations planned in 0.15 seconds, zero model calls — that's the
> answer to 'does this scale'. ₹84,000 of household cost avoided, 6,275 km of
> travel removed, 183 of those plans need no travel at all."

Point at the green verification banner:

> "Every one of those is appended to a hash-chained, Ed25519-signed ledger.
> You don't have to believe me — fetch the chain, recompute the hashes, verify
> against the published public key. If I'd edited a number to flatter myself,
> that banner would be red."

> "And nothing closes without evidence. A blood-pressure value, a dispensing
> record, a test result. 'Patient counselled' closes nothing. There is no API
> through which an obligation can be marked done without evidence — that
> absence is the feature."

## 2:45 — The trial, if you have the time (30s)

If your video can run to 3.5 minutes, this is the strongest 30 seconds in it.
Go to **The trial**, hit **Run the trial**.

> "Everything I've shown you so far is my own model talking about itself. So:
> ninety days, two arms, same population, same effort budget. And the outcomes
> are drawn from a *different* behavioural model than the planner optimises
> against — perturbed 35% — because if I graded the planner against its own
> beliefs, 'Nirantar wins' would be arithmetic, not a finding."

> "1.7× more obligations closed, at 21% of the household cost per closure,
> ahead in all three worlds. And the backlog actually burns down — the status
> quo line barely moves."

Then scroll to the equity section — this is the bit that builds trust:

> "An efficiency objective wants to work the easy cases. So we audited it.
> Village routing closes the distance gap completely: the furthest quintile
> ends up served as often as the nearest. The wage gap we did *not* close —
> it's 1.42 in the status quo and 1.40 here. The weighting narrows it from
> 1.69 to 1.40 and costs us 6% of total closures. That's a real trade-off and
> I'm showing it to you as one."

## 3:15 — The field app (20s)

> "Last thing. A district dashboard is for someone with a laptop. This is for
> the ASHA who actually walks to the house."

Switch your network off, mark something done.

> "One household per card, not one obligation — so she's never sent to the
> same courtyard twice. The evidence bar is on the card before she sets off.
> And it's offline: that just queued on the handset and will sync when a
> signal comes back. 1.6 KB per household, under four seconds for her whole
> queue on 2G."

## 3:35 — Close (15s)

Go to **Method & sources** briefly.

> "Every constant is published with its source, including the ones we had to
> assume, and the limits are written down: the district is simulated, the
> savings are modelled predictions rather than measured outcomes, and the
> vernacular copy needs a native speaker before a single call goes out."

> "Apache-2.0, FHIR-shaped, and it derives from Observation records that
> already exist in the NCD portal. It needs no new data collection. The
> abnormal results are already sitting there."

---

## If you have 30 extra seconds

Two things worth showing:

- **The rejections.** *What the planner considered* lists every option it
  priced and threw away, with reasons — "no staff currently posted", "no
  appointment slot inside the clinical deadline". A recommendation you can't
  interrogate isn't a recommendation.
- **The escalations.** On *The gap*, hit **Write briefs**. Clusters ranked by
  harm accumulating, each with the specific administrative fix a Block
  Medical Officer can authorise this week. And note: escalations are raised
  against *system* failures. "Non-compliant patient" isn't a category
  anywhere in this codebase.

## Recording notes

**The live demo is at https://nirantar-zbyj.onrender.com.** It is on free
hosting, so it spins down after ~15 minutes idle and the first request then
takes ~50 seconds. Open it a minute before you record or present.

Free hosting also means a fraction of a CPU: the controlled trial takes a few
seconds locally and up to a minute there. It defaults to one world for that
reason, and shows a running elapsed counter so it is visibly working. If you
are recording, either run it locally or start it and talk over it.


- Run `make build` first so the backend serves the production bundle.
- `make shots` captures stills if you want cutaways.
- Dark mode records better on a projector; light mode reads better embedded in
  a page.
- The seed is fixed (`DATA_SEED=20260815`), so the district is identical on
  every run — your narration will match what's on screen take after take.
- With `ANTHROPIC_API_KEY` set, the trace rows show a "Claude" badge and the
  prose is model-written. Without it, everything still runs. Either is a fine
  demo; say which one you're showing.
