# Voiceover cue sheet — `demo.mp4`

**1920×1080 · 3:44 · silent** (recorded with no audio track, for you to narrate).

Timestamps are against `demo.mp4`. Read the right-hand column over the
matching shot; the wording is paced to how long each shot is held. Every
figure quoted was read off this recording — nothing here claims a number the
footage doesn't show.

| Time | On screen | Say |
|---|---|---|
| **00:00** | Hero — the claim | India screens superbly and follows up terribly. Tens of crores screened for hypertension, diabetes and three cancers. Roughly one in eight Indian adults with hypertension actually has it controlled. The diagnosis was right and the medicine costs rupees — what's missing is the step between *we found your problem* and *we treated your problem*. That isn't a clinical problem. It's a logistics problem. |
| **00:07** | Headline numbers | In this one block, 2,727 people are owed care right now — eleven percent of the population — and 2,611 of them are already past their clinical deadline. |
| **00:14** | The screening cascade | 9,411 people screened. 4,660 abnormal results found. 1,175 actually treated. Everyone in that gap was found by the system and then dropped by it. |
| **00:23** | What a follow-up really costs | Here's why reminder apps don't work. The average follow-up costs the household ₹367 and a 22 km round trip — a day's wages. Half of these people are predicted not to attend, and the top barrier isn't motivation: the system doesn't speak their language, they live 25 km from the hospital, and the trip costs more than they earn in a day. Existing referral software prices that visit at zero and then records non-attendance as the patient's fault. |
| **00:32** | Block schematic | And the two panchayats furthest from the district hospital are exactly the two the mobile medical units never reach. |
| **00:38** | The worklist | This is the block's worklist, ordered by expected harm if never closed — not by date received. |
| **00:45** | The case | Bhola Pal. Sixty-six, confirmed TB, treatment never started, two hundred and thirteen days past the clinical deadline. No phone in the household. Speaks Santali. |
| **00:52** | The agent trace | Five agents. Triage ranks by harm. Reality prices what a conventional referral would cost him — ₹641, and a seventy-two percent chance he doesn't go. Supply finds what can actually treat him, with the drug in stock. Planner optimises. Verifier sets the evidence bar. Sub-millisecond, and no model calls needed. |
| **01:01** | The counterfactual | ₹641 down to ₹368. Seventy-two percent chance of not attending, down to thirty-two. ₹273 back in the household, and he's more than twice as likely to actually start treatment. |
| **01:12** | Outreach — a person at the door | Three things worth pointing out. He has no phone — so outreach isn't a call or an SMS, it's a health worker walking to his house. And he speaks Santali, but we only have copy in Hindi and Bhojpuri. The system flags that, and it *keeps the language penalty in the prediction*. We don't take credit for a barrier we didn't remove. |
| **01:20** | What it rejected | This is everything the planner threw away, with reasons. It refused the mobile van — cheaper and closer — because starting TB treatment means registering him on the national programme, and a van can't do that. Cheap only wins where the care is genuinely equivalent. |
| **01:29** | Barriers | Every barrier named, measured and actionable — not a judgement about motivation. |
| **01:35** | The Impact Ledger | Judging asks for proven impact, not intentions. So measurement is a feature here, not a slide. |
| **01:41** | 300 obligations planned | Three hundred obligations planned in under four seconds, zero model calls — that's the answer to whether this scales. ₹84,000 of household cost avoided, 6,700 km of travel removed. |
| **01:48** | Chain verified | All of it appended to a hash-chained, Ed25519-signed ledger. You don't have to believe me — fetch the chain, recompute the hashes, verify against the published public key. If I'd edited a number to flatter myself, that banner would be red. And nothing closes without evidence: a blood-pressure value, a dispensing record, a test result. 'Patient counselled' closes nothing. |
| **01:57** | The chain itself | Hash-chained, signed, and carrying no names, phone numbers or villages. |
| **02:02** | The controlled trial | Everything so far is my own model talking about itself. So: ninety days, two arms, same population, same effort budget. The outcomes are drawn from a *different* behavioural model than the planner optimises against, perturbed thirty-five percent — because if I graded the planner against its own beliefs, 'Nirantar wins' would be arithmetic, not a finding. |
| **02:14** | Trial result | One-point-seven times more obligations closed, at twenty-one percent of the household cost per closure, and ahead in every world we tried. |
| **02:23** | Burn-down | And the backlog actually burns down. The status-quo line barely moves. |
| **02:32** | Calibration | We publish how wrong the predictions were, too — a reliability diagram and a Brier score. |
| **02:38** | The equity audit | An efficiency objective wants to work the easy cases, so we audited it. Village routing closes the distance gap completely — the furthest quintile ends up served as often as the nearest. The wage gap we did *not* close. The weighting narrows it, and it costs six percent of total closures. That's a real trade-off, shown as one. |
| **02:49** | The field app | Last thing. A district dashboard is for someone with a laptop. This is for the ASHA who actually walks to the house. One household per card, not one obligation — so she's never sent to the same courtyard twice. |
| **02:55** | The 2G budget | One-point-six kilobytes per household. Under four seconds for her whole queue on a 2G link. |
| **03:01** | Network switched OFF | Now watch — I'm taking the network away. |
| **03:06** | Saved on the handset | That just queued on the phone. An app that needs a signal to record a completed visit doesn't get used. |
| **03:17** | Back online — synced | And back online, it flushes straight into the signed ledger. |
| **03:23** | Method & sources | Every constant published with its source, including the ones we had to assume. |
| **03:30** | Limits, stated plainly | And the limits are written down: the district is simulated, the savings are modelled predictions rather than measured outcomes, and the vernacular copy needs a native speaker before a single call goes out. |
| **03:38** | Close | Apache-2.0, FHIR-shaped, and it derives from Observation records that already exist in the NCD portal. It needs no new data collection — the abnormal results are already sitting there. |

## Notes

- **The video is silent.** Add your voiceover in QuickTime, iMovie, CapCut or
  DaVinci Resolve — whatever you have.
- Runs 3:44. If you need it under three minutes, the cleanest cuts are
  *The chain itself*, *Calibration* and *Method & sources* — each is a held
  shot you can trim without breaking the narrative.
- To re-record: `cd frontend && node scripts/record-demo.mjs --pace 0.8`.
  Restart the backend first so the world is pristine — a depleted world (vans
  booked, ASHA capacity used up by earlier runs) produces visibly weaker
  plans.
- The live demo is at <https://nirantar-zbyj.onrender.com> if you would rather
  present than play the video. Wake it a minute beforehand: free hosting
  sleeps after fifteen minutes idle.

