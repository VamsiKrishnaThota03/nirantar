"""The trial has to be a fair test, so the fairness is itself tested.

A simulation that flatters its own system is worse than no simulation,
because it launders an assumption into something that looks like evidence.
These tests pin the properties that make the comparison honest.
"""

from __future__ import annotations

import random

import pytest

from nirantar import simulation
from nirantar.simulation import TruthModel, calibration, compare, equity, run_trial


def _truth(seed: int = 7, scale: float = 0.35) -> TruthModel:
    return TruthModel.perturbed(random.Random(seed), scale=scale)


# --- fairness of the design -----------------------------------------------


def test_the_truth_model_is_not_the_planners_model():
    """The core anti-circularity property.

    If the world ran on the same coefficients the planner optimises against,
    "Nirantar wins" would be arithmetic rather than evidence.
    """
    believed = TruthModel.as_believed()
    perturbed = _truth()
    differing = sum(
        1
        for key, value in believed.as_dict().items()
        if key != "perturbation_scale" and perturbed.as_dict()[key] != value
    )
    assert differing >= 8, (
        "the ground-truth coefficients are barely perturbed from the "
        "planner's beliefs, so the trial is close to grading the planner "
        "against itself"
    )


def test_both_arms_get_the_same_effort_budget(app_state):
    """Equal effort, different targeting and different offers.

    If one arm were allowed more daily contacts the comparison would measure
    budget rather than system design.
    """
    truth = _truth()
    status_quo = run_trial(arm="status_quo", truth=truth, days=20, draw_seed=5)
    nirantar = run_trial(arm="nirantar", truth=truth, days=20, draw_seed=5)
    # Budgets are a share of each arm's own live backlog, so they diverge as
    # the backlogs diverge -- but on day one, before any divergence, they
    # must be identical.
    assert status_quo.days[0].contacts_made > 0
    assert nirantar.days[0].contacts_made > 0
    assert abs(
        status_quo.days[0].contacts_made - nirantar.days[0].contacts_made
    ) <= max(2, int(0.1 * status_quo.days[0].contacts_made)), (
        "the two arms started with materially different contact budgets"
    )


def test_the_status_quo_arm_is_not_a_straw_man(app_state):
    """Its attendance rate must land in a defensible band.

    Published cascades imply conventional referral completion somewhere
    around a third. If this arm collapsed to near zero, the comparison would
    be rigged and every headline derived from it worthless.
    """
    rates = []
    for index in range(3):
        truth = _truth(seed=20 + index)
        result = run_trial(
            arm="status_quo", truth=truth, days=60, draw_seed=100 + index
        )
        rates.append(result.summary()["attendance_rate"])
    assert all(0.05 <= rate <= 0.60 for rate in rates), (
        f"status-quo attendance rates {rates} are outside any defensible "
        "band for conventional referral completion"
    )


def test_a_trial_never_writes_to_the_impact_ledger(app_state):
    """Simulated outcomes must not contaminate the signed record."""
    before = app_state.ledger.count()
    run_trial(arm="nirantar", truth=_truth(), days=20, draw_seed=3)
    compare(days=20, trials=1)
    assert app_state.ledger.count() == before


def test_a_trial_does_not_mutate_the_live_demo_world(app_state):
    """Each trial generates its own block."""
    open_before = len(app_state.world.open_debts())
    booked_before = sum(w.booked for w in app_state.world.outreach.values())
    run_trial(arm="nirantar", truth=_truth(), days=30, draw_seed=4)
    assert len(app_state.world.open_debts()) == open_before
    assert sum(w.booked for w in app_state.world.outreach.values()) == booked_before


def test_capacity_still_binds_inside_a_trial(app_state):
    """Otherwise the trial would show unlimited throughput."""
    truth = _truth()
    result = run_trial(arm="nirantar", truth=truth, days=90, draw_seed=6)
    summary = result.summary()
    # Not everything can be closed: vans, slots and health workers are finite.
    assert summary["still_open"] > 0, (
        "the trial closed the entire backlog, which means a capacity "
        "constraint is not binding and the simulation is too generous"
    )


# --- outcomes --------------------------------------------------------------


def test_the_optimiser_helps_even_when_the_world_differs_from_the_model():
    """The actual research question, asserted across perturbed worlds."""
    result = compare(days=60, trials=3)
    multiples = [row["closure_multiple"] for row in result["trials"]]
    assert all(value > 1.0 for value in multiples), (
        f"closure multiples {multiples}: the optimiser failed to beat a "
        "due-date queue in at least one perturbed world"
    )
    assert result["aggregate"]["cost_per_closure_ratio"]["median"] < 1.0, (
        "Nirantar did not reduce the cost per closure borne by households"
    )


def test_calibration_is_reported_rather_than_assumed():
    """We publish how wrong the predictions were."""
    truth = _truth()
    result = run_trial(arm="nirantar", truth=truth, days=60, draw_seed=8)
    rows = calibration(result)
    assert rows
    for row in rows:
        assert set(row) >= {"predicted_no_show", "realised_no_show", "error", "n"}
    # There should be real error somewhere: a perfectly calibrated model
    # against a deliberately perturbed world would mean the perturbation is
    # not doing anything.
    assert max(abs(row["error"]) for row in rows) > 0.01


def test_brier_score_is_finite_and_bounded():
    result = run_trial(arm="nirantar", truth=_truth(), days=30, draw_seed=9)
    score = simulation.brier_score(result)
    assert 0.0 <= score <= 1.0


# --- equity ----------------------------------------------------------------


def test_equity_is_measured_over_everyone_owed_care(app_state):
    """Not merely over those the system managed to contact.

    Measuring against contacts made was an earlier bug: it saturated at
    1.000 for the Nirantar arm and hid the question entirely.
    """
    result = run_trial(arm="nirantar", truth=_truth(), days=60, draw_seed=11)
    report = equity(result)
    assert report["people_owed_care"] > report["people_contacted"], (
        "every person owed care was contacted, so the daily budget is not "
        "binding and the equity denominator is not meaningful"
    )
    assert 0.0 < report["overall_served_rate"] < 1.0


def test_village_routing_closes_the_distance_gap():
    """The clearest equity win, and it should be visible in the numbers."""
    truth = _truth(seed=31)
    status_quo = run_trial(arm="status_quo", truth=truth, days=90, draw_seed=12)
    nirantar = run_trial(arm="nirantar", truth=truth, days=90, draw_seed=12)
    sq_ratio = equity(status_quo)["nearest_over_furthest_ratio"]
    ni_ratio = equity(nirantar)["nearest_over_furthest_ratio"]
    assert sq_ratio is not None and ni_ratio is not None
    # Status quo favours the nearest; Nirantar should not.
    assert sq_ratio > 1.0, (
        f"status-quo distance ratio {sq_ratio} does not show the expected "
        "bias toward patients living closer to the hospital"
    )
    assert ni_ratio < sq_ratio, (
        f"Nirantar distance ratio {ni_ratio} is no better than the status "
        f"quo's {sq_ratio}; village routing should narrow this gap"
    )


def test_the_equity_weighting_actually_changes_who_gets_served():
    """An equity mechanism that changes nothing is decoration.

    Also records the cost: the weighting is expected to close slightly fewer
    obligations in total, which is a real trade-off rather than a free win.
    """
    truth = _truth(seed=41)
    weighted = run_trial(
        arm="nirantar", truth=truth, days=90, draw_seed=13, equity_weighting=True
    )
    unweighted = run_trial(
        arm="nirantar", truth=truth, days=90, draw_seed=13, equity_weighting=False
    )
    weighted_gap = equity(weighted)["richest_over_poorest_ratio"]
    unweighted_gap = equity(unweighted)["richest_over_poorest_ratio"]
    assert weighted_gap is not None and unweighted_gap is not None
    assert weighted_gap < unweighted_gap, (
        f"the vulnerability weighting left the wage gap unchanged "
        f"({weighted_gap} vs {unweighted_gap}); it is not doing its job"
    )


def test_zero_wage_households_are_inside_the_equity_weighting():
    """Regression: a truthiness check once excluded them.

    `if person.daily_wage_inr and person.daily_wage_inr < 350` skipped
    everyone earning exactly zero -- homemakers and children, which is the
    group the weighting most needed to cover.
    """
    from nirantar.agents.triage import vulnerability_multiplier
    from nirantar.models import Person, PhoneType

    homemaker = Person(
        id="p-zero",
        display_name="Test Person",
        age=30,
        sex="female",
        panchayat="Amraulia",
        village="Amraulia",
        language="Hindi",
        literacy="basic",
        phone_type=PhoneType.FEATURE,
        daily_wage_inr=0.0,
        occupation="homemaker",
        caregiver_available=True,
        km_to_subcentre=1.0,
        km_to_phc=5.0,
        km_to_chc=10.0,
        km_to_district=20.0,
    )
    multiplier, reasons = vulnerability_multiplier(homemaker)
    assert multiplier > 1.0
    assert any("wage" in reason for reason in reasons)


# --- the endpoint ----------------------------------------------------------


def test_trial_endpoint_returns_a_complete_report(client):
    response = client.post("/api/trial", json={"days": 30, "trials": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    for key in ("design", "trials", "aggregate", "burn_down", "calibration", "equity"):
        assert key in body, key
    assert len(body["burn_down"]["status_quo"]) == 30
    assert len(body["burn_down"]["nirantar"]) == 30
    # The caveat must travel with the numbers.
    assert "not a field trial" in body["design"]["not_a_claim_of_real_impact"]
    assert body["equity"]["ablation"]


def test_trial_endpoint_rejects_an_absurd_horizon(client):
    assert client.post("/api/trial", json={"days": 9999}).status_code == 422
    assert client.post("/api/trial", json={"trials": 500}).status_code == 422
