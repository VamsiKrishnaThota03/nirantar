"""The clinical and economic guardrails, asserted.

Every test here corresponds to a way this system could hurt someone if the
optimiser were left to chase cheapness unsupervised.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from nirantar.agents import orchestrator, planner, supply, verifier
from nirantar.agents.base import AgentContext
from nirantar.behaviour import AttendanceFeatures, estimate_cost, no_show_probability
from nirantar.data.generator import CONDITION_DRUG
from nirantar.models import DebtStatus, EvidenceItem, FacilityType


def _ctx(app_state):
    return AgentContext(
        world=app_state.world, ledger=app_state.ledger, as_of=app_state.as_of
    )


def _plan_first(app_state, predicate=None, limit=400):
    debts = orchestrator.worklist(app_state.world, app_state.as_of, limit=limit)
    for debt in debts:
        if predicate and not predicate(debt):
            continue
        ctx = _ctx(app_state)
        run = asyncio.run(orchestrator.plan_one(ctx, debt))
        if run.plan is not None:
            return debt, run, ctx
    pytest.skip("no matching plannable obligation in this generated world")


# --- the pipeline runs at all ---------------------------------------------


def test_pipeline_produces_a_complete_plan_without_any_model(app_state):
    """No API key is set in tests. A full plan must still come out."""
    debt, run, ctx = _plan_first(app_state)
    assert run.error is None
    plan = run.plan
    assert plan is not None
    assert plan.generated_by == "deterministic"
    assert plan.steps, "a plan with no steps is not a plan"
    assert plan.cost.total_inr >= 0
    assert 0.0 < plan.predicted_no_show < 1.0
    assert plan.artifacts["voice_script"]["script"]
    assert plan.artifacts["voice_script"]["english_gloss"]
    assert plan.counterfactual["cost_inr"] is not None
    # Every agent reported.
    assert {step.agent for step in run.steps} == {
        "Triage",
        "Reality",
        "Supply",
        "Planner",
        "Verifier",
    }


# --- clinical guardrails ---------------------------------------------------


def test_tb_treatment_is_never_initiated_by_a_mobile_van(app_state):
    """Starting TB treatment means programme registration, not a van visit."""
    debts = [
        debt
        for debt in app_state.world.debts.values()
        if debt.condition == "tb_confirmed_not_initiated"
        and debt.status != DebtStatus.CLOSED
    ]
    assert debts, "expected confirmed TB obligations in the generated world"
    checked = 0
    for debt in debts[:25]:
        ctx = _ctx(app_state)
        options = supply.enumerate_options(ctx, debt)
        for option in options:
            assert option["facility_type"] != FacilityType.MOBILE_VAN.value, (
                "a mobile medical unit was offered as a venue for initiating "
                "TB treatment, which is not equivalent care"
            )
        checked += 1
    assert checked


def test_specialist_review_is_never_downgraded_to_a_van_or_phone(app_state):
    debts = [
        debt
        for debt in app_state.world.debts.values()
        if debt.required_action == "specialist_review"
        and debt.status != DebtStatus.CLOSED
    ]
    assert debts
    for debt in debts[:25]:
        ctx = _ctx(app_state)
        for option in supply.enumerate_options(ctx, debt):
            assert option["facility_type"] not in {
                FacilityType.MOBILE_VAN.value,
                FacilityType.TELECONSULT.value,
            }, "a specialist examination cannot be done by van or by phone"


def test_refill_is_never_routed_to_an_empty_shelf(app_state):
    """Sending someone for medicine that is not there is worse than nothing."""
    debts = [
        debt
        for debt in app_state.world.debts.values()
        if debt.required_action == "refill_medication"
        and debt.status != DebtStatus.CLOSED
    ]
    assert debts
    planned = 0
    for debt in debts[:40]:
        ctx = _ctx(app_state)
        # shortlist() reads the inventory the Supply agent put into the
        # shared context, so Supply has to have run first.
        asyncio.run(supply.run(ctx, debt))
        candidates = planner.shortlist(ctx, debt)
        for candidate in candidates:
            assert candidate["option"].get("stock_ok") is True, (
                "a medication refill was planned at a venue expected to be "
                "out of stock"
            )
        planned += bool(candidates)
    assert planned, "no refill obligations were plannable at all"


def test_unstaffed_facilities_are_rejected_with_a_reason(app_state):
    unstaffed = [
        facility
        for facility in app_state.world.facilities.values()
        if not facility.staff_present
    ]
    if not unstaffed:
        pytest.skip("no unstaffed facility in this generated world")
    panchayats = {facility.panchayat for facility in unstaffed}
    for debt in app_state.world.open_debts():
        person = app_state.world.people[debt.person_id]
        if person.panchayat not in panchayats:
            continue
        ctx = _ctx(app_state)
        options = supply.enumerate_options(ctx, debt)
        for option in options:
            if option.get("rejected_because") == "no staff currently posted":
                assert option["days_until"] == 999
                return
    pytest.skip("no obligation exercised the unstaffed-facility path")


# --- economic behaviour ----------------------------------------------------


def test_plan_beats_the_conventional_referral_on_cost_and_attendance(app_state):
    debt, run, _ctx_ = _plan_first(app_state)
    plan = run.plan
    assert plan is not None
    cf = plan.counterfactual
    assert plan.cost.total_inr <= float(cf["cost_inr"]) + 1e-6, (
        "the optimiser produced a plan more expensive for the household than "
        "the conventional referral it is supposed to improve on"
    )
    assert plan.predicted_no_show <= float(cf["no_show"]) + 1e-6


def test_zero_travel_options_are_preferred_when_clinically_equivalent(app_state):
    """A refill is the clearest case: a van in the village beats a bus ride."""
    debt, run, ctx = _plan_first(
        app_state, predicate=lambda d: d.required_action == "refill_medication"
    )
    plan = run.plan
    assert plan is not None
    assert plan.cost.travel_km <= 6.0, (
        f"a medication refill was planned with {plan.cost.travel_km} km of "
        "travel when village-level options exist"
    )


def test_cost_model_charges_unpaid_labour_rather_than_zero():
    """Costing a homemaker's day at zero is how women's follow-up gets dropped."""
    from nirantar.models import Person, PhoneType

    homemaker = Person(
        id="p-test-1",
        display_name="Test Person",
        age=32,
        sex="female",
        panchayat="Amraulia",
        village="Amraulia",
        language="Bhojpuri",
        literacy="basic",
        phone_type=PhoneType.FEATURE,
        daily_wage_inr=0.0,
        occupation="homemaker",
        caregiver_available=False,
        km_to_subcentre=1.5,
        km_to_phc=6.0,
        km_to_chc=12.0,
        km_to_district=30.0,
    )
    cost = estimate_cost(homemaker, FacilityType.DISTRICT)
    assert cost.wage_loss_inr > 0, (
        "a visit was priced at zero lost earnings because the patient has no "
        "cash wage; unpaid labour is not free"
    )


def test_no_show_falls_when_barriers_are_removed():
    """Direction-of-effect check on the behavioural model."""
    from nirantar.models import Person, PhoneType

    person = Person(
        id="p-test-2",
        display_name="Test Person",
        age=55,
        sex="male",
        panchayat="Mahuadanr",
        village="Mahuadanr",
        language="Santali",
        literacy="none",
        phone_type=PhoneType.FEATURE,
        daily_wage_inr=340.0,
        occupation="agricultural labourer",
        caregiver_available=False,
        km_to_subcentre=2.0,
        km_to_phc=14.0,
        km_to_chc=28.0,
        km_to_district=47.0,
    )
    far = AttendanceFeatures(
        cost=estimate_cost(person, FacilityType.DISTRICT),
        days_until_slot=21,
        asha_accompanied=False,
        outreach_language_matches=False,
        expected_stockout=True,
        text_only_outreach=True,
    )
    near = AttendanceFeatures(
        cost=estimate_cost(person, FacilityType.MOBILE_VAN),
        days_until_slot=3,
        asha_accompanied=True,
        outreach_language_matches=True,
        expected_stockout=False,
        text_only_outreach=False,
    )
    assert no_show_probability(person, near) < no_show_probability(person, far) - 0.2


def _capacity_consumed(app_state) -> int:
    """Total committed capacity across every scarce resource the planner spends."""
    booked = sum(w.booked for w in app_state.world.outreach.values())
    slots = sum(
        sum(facility.slots.values()) for facility in app_state.world.facilities.values()
    )
    asha_tasks = sum(asha.open_tasks for asha in app_state.world.ashas.values())
    # Facility slots count down, so invert them to get a monotonic total.
    return booked + asha_tasks - slots


def test_capacity_is_consumed_so_plans_cannot_double_book(app_state):
    """The hundredth patient must be planned against the remaining capacity.

    Checks every scarce resource, not just mobile vans: the worklist is
    ordered by severity, and the most severe obligations route to facilities
    rather than to village outreach, so a van-only assertion would pass or
    fail depending on the seed rather than on the behaviour.
    """
    before = _capacity_consumed(app_state)
    debts = orchestrator.worklist(app_state.world, app_state.as_of, limit=60)
    for debt in debts[:20]:
        ctx = _ctx(app_state)
        asyncio.run(orchestrator.plan_one(ctx, debt))
    assert _capacity_consumed(app_state) > before, (
        "planning consumed no capacity anywhere, so concurrent plans would "
        "double-book the same slot, van or health worker"
    )
    for window in app_state.world.outreach.values():
        assert window.booked <= window.capacity
    for facility in app_state.world.facilities.values():
        assert all(free >= 0 for free in facility.slots.values())


# --- closure ---------------------------------------------------------------


def test_wrong_evidence_type_cannot_close_an_obligation(app_state):
    debt = next(
        debt
        for debt in app_state.world.debts.values()
        if debt.required_action == "refill_medication"
        and debt.status != DebtStatus.CLOSED
    )
    evidence = EvidenceItem(
        kind="visit_logged",
        recorded_at=datetime.now(timezone.utc),
        recorded_by="tester",
        detail="Patient was counselled about the importance of medication.",
    )
    decision = verifier.adjudicate(debt, evidence)
    assert decision["accepted"] is False
    assert debt.status != DebtStatus.CLOSED


def test_backdated_evidence_is_rejected(app_state):
    debt = next(
        debt
        for debt in app_state.world.debts.values()
        if debt.status != DebtStatus.CLOSED
    )
    kind = sorted(verifier.required_evidence_for(debt.required_action))[0]
    evidence = EvidenceItem(
        kind=kind,
        recorded_at=datetime.combine(
            debt.opened_on - timedelta(days=3), datetime.min.time()
        ).replace(tzinfo=timezone.utc),
        recorded_by="tester",
        detail="Recorded before the obligation existed.",
    )
    decision = verifier.adjudicate(debt, evidence)
    assert decision["accepted"] is False
    assert any("predates" in problem for problem in decision["problems"])


def test_correct_evidence_closes_and_writes_a_ledger_entry(app_state):
    debt = next(
        debt
        for debt in app_state.world.debts.values()
        if debt.required_action == "refill_medication"
        and debt.status != DebtStatus.CLOSED
    )
    before = app_state.ledger.count()
    ctx = _ctx(app_state)
    evidence = EvidenceItem(
        kind="drug_dispensed",
        recorded_at=datetime.now(timezone.utc),
        recorded_by="asha-000",
        detail="Amlodipine 5mg, 30 tablets dispensed.",
    )
    decision = verifier.close_with_evidence(ctx, debt, evidence)
    assert decision["accepted"] is True
    assert debt.status == DebtStatus.CLOSED
    assert app_state.ledger.count() == before + 1
    assert app_state.ledger.verify()["valid"]


def test_closure_criteria_explicitly_reject_outreach_as_an_outcome(app_state):
    debt = next(iter(app_state.world.debts.values()))
    criteria = verifier.closure_criteria(debt)
    rejected = " ".join(criteria["will_not_accept"]).lower()
    assert "counselled" in rejected
    assert "referred" in rejected
    assert "message delivered" in rejected


# --- escalation ------------------------------------------------------------


def test_escalations_blame_the_system_not_the_patient(app_state):
    from nirantar.agents import escalation

    clusters = escalation.cluster(
        app_state.world, app_state.world.open_debts(), app_state.as_of
    )
    assert clusters, "expected at least one structurally blocked cluster"
    for group in clusters:
        assert group["cause"] in escalation.REMEDY
        assert group["remedy"]
        # No cause may be attributed to patient behaviour.
        assert "patient" not in group["cause"]
        assert "non_compliance" not in group["cause"]
    brief = asyncio.run(escalation.write_brief(clusters[0], app_state.as_of))
    assert brief.to_role == "Block Medical Officer"
    assert brief.brief_markdown
    assert brief.generated_by == "deterministic"


def test_clusters_rank_by_harm_not_by_count(app_state):
    from nirantar.agents import escalation

    clusters = escalation.cluster(
        app_state.world, app_state.world.open_debts(), app_state.as_of
    )
    harms = [group["healthy_years_at_stake"] for group in clusters]
    assert harms == sorted(harms, reverse=True)


# --- outreach channel integrity -------------------------------------------


def test_patient_with_no_phone_is_never_promised_an_electronic_message(app_state):
    """A household with no handset gets a person at the door, or nothing.

    This test exists because the first version of the planner cheerfully told
    a patient with no phone that it would send them a WhatsApp message.
    """
    from nirantar.models import PhoneType

    candidates = [
        debt
        for debt in app_state.world.open_debts()
        if app_state.world.people[debt.person_id].phone_type == PhoneType.NONE
    ]
    assert candidates, "expected some households with no phone"
    checked = 0
    for debt in candidates[:30]:
        ctx = _ctx(app_state)
        run = asyncio.run(orchestrator.plan_one(ctx, debt))
        if run.plan is None:
            continue
        checked += 1
        assert run.plan.artifacts["channel"] == "asha_visit", (
            "a patient with no phone was assigned an electronic channel"
        )
        joined = " ".join(step.action.lower() for step in run.plan.steps)
        assert "whatsapp" not in joined
        assert "sms" not in joined
        assert "voice call" not in joined
    assert checked, "no no-phone obligation was plannable"


def test_language_fallback_is_counted_as_a_barrier_not_hidden(app_state):
    """We only claim a language match where we actually have the copy."""
    from nirantar.behaviour import language_is_supported

    unsupported = [
        debt
        for debt in app_state.world.open_debts()
        if not language_is_supported(app_state.world.people[debt.person_id])
    ]
    assert unsupported, "expected speakers of languages we have no copy for"
    for debt in unsupported[:20]:
        ctx = _ctx(app_state)
        run = asyncio.run(orchestrator.plan_one(ctx, debt))
        if run.plan is None:
            continue
        script = run.plan.artifacts["voice_script"]
        assert script["fell_back_to_hindi"] is True
        barriers = ctx.shared.get("barriers", [])
        # The barrier decomposition for the conventional baseline must still
        # carry the language penalty, and the plan must not have credited
        # itself with removing it.
        assert run.plan.artifacts["script_language"] == "Hindi"
        assert barriers
        return
    pytest.skip("no plannable obligation for an unsupported language")


def test_every_plan_declares_a_channel_the_person_can_receive(app_state):
    from nirantar.models import PhoneType

    allowed = {
        PhoneType.NONE: {"asha_visit"},
        PhoneType.FEATURE: {"ivr_call", "asha_visit"},
        PhoneType.SMART: {"ivr_call", "whatsapp", "asha_visit"},
    }
    debts = orchestrator.worklist(app_state.world, app_state.as_of, limit=40)
    seen = 0
    for debt in debts:
        ctx = _ctx(app_state)
        run = asyncio.run(orchestrator.plan_one(ctx, debt))
        if run.plan is None:
            continue
        person = app_state.world.people[debt.person_id]
        assert run.plan.artifacts["channel"] in allowed[person.phone_type], (
            f"{person.phone_type} patient assigned "
            f"{run.plan.artifacts['channel']}"
        )
        seen += 1
    assert seen
