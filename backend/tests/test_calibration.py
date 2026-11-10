"""Guards the honesty of the simulation.

The claim this project makes is that the generated district behaves like a
real one. These tests are what make that claim falsifiable: if a change
drifts the simulated screening cascade away from the published Indian
figures, the build fails. Without them, "calibrated to NFHS-5" is a sentence
in a README rather than a property of the code.
"""

from __future__ import annotations

from nirantar import calibration as cal


def test_every_constant_declares_its_provenance():
    for item in cal.all_sources():
        assert item["source"].strip(), f"{item['constant']} has no source"
        # Assumptions are allowed; undeclared assumptions are not.
        if item["source"] == "ASSUMED":
            assert item["note"].strip(), (
                f"{item['constant']} is assumed but carries no explanation. "
                "An assumption nobody can argue with is not a model, it is a "
                "magic number."
            )


def test_every_condition_has_a_deadline_and_a_severity(app_state):
    conditions = {debt.condition for debt in app_state.world.debts.values()}
    for condition in conditions:
        assert condition in cal.CLINICAL_DEADLINE_DAYS
        assert condition in cal.SEVERITY_DALY_WEIGHT
        assert condition in cal.HUMAN_LABEL


def test_screening_coverage_matches_published_rate(app_state):
    adults = [p for p in app_state.world.people.values() if p.age >= 18]
    coverage = app_state.world.people_screened / max(1, len(adults))
    # Population-based screening coverage is modelled at 55% of adults.
    assert 0.48 <= coverage <= 0.62, f"screening coverage drifted to {coverage:.3f}"


def test_hypertension_prevalence_tracks_nfhs(app_state):
    """Among screened adults, how many were found hypertensive."""
    adults_screened = app_state.world.people_screened
    htn = sum(
        1
        for debt in app_state.world.debts.values()
        if debt.condition.startswith("hypertension")
    )
    rate = htn / max(1, adults_screened)
    expected = (cal.HTN_PREVALENCE_MEN.value + cal.HTN_PREVALENCE_WOMEN.value) / 2
    assert abs(rate - expected) < 0.05, (
        f"simulated hypertension detection rate {rate:.3f} has drifted from "
        f"the NFHS-5 anchor of {expected:.3f}"
    )


def test_tb_initial_loss_to_followup_matches_published_rate(app_state):
    """TB does comparatively well, because the TB programme chases patients.

    If this test ever passes trivially it means the simulation has stopped
    distinguishing an actively-managed programme from a passive one, and the
    whole premise of the project would be unfalsifiable.
    """
    tb = [
        debt
        for debt in app_state.world.debts.values()
        if debt.condition == "tb_confirmed_not_initiated"
    ]
    assert tb, "no confirmed TB obligations generated"
    closed = sum(1 for debt in tb if debt.status.value == "closed")
    closure_rate = closed / len(tb)
    expected = 1.0 - cal.TB_INITIAL_LOSS_TO_FOLLOWUP.value
    # Wide band: distance and poverty modifiers legitimately pull this down.
    assert 0.55 <= closure_rate <= expected + 0.05, (
        f"TB treatment initiation rate {closure_rate:.3f} is implausible "
        f"against a published initial-loss-to-follow-up of "
        f"{cal.TB_INITIAL_LOSS_TO_FOLLOWUP.value:.3f}"
    )


def test_ncd_follow_up_is_far_worse_than_tb(app_state):
    """The central empirical claim of the project, asserted as a test.

    India closes TB obligations far more often than it closes hypertension
    obligations, because one has an active chase mechanism and the other has
    a screening camp and a hope. If this inequality ever inverts in the
    model, the model is no longer describing India.
    """

    def closure_rate(prefix: str) -> float:
        members = [
            debt
            for debt in app_state.world.debts.values()
            if debt.condition.startswith(prefix)
        ]
        closed = sum(1 for debt in members if debt.status.value == "closed")
        return closed / max(1, len(members))

    tb_rate = closure_rate("tb_confirmed")
    htn_rate = closure_rate("hypertension")
    assert tb_rate > htn_rate + 0.3, (
        f"TB closure {tb_rate:.2f} vs hypertension closure {htn_rate:.2f}: "
        "the simulation has lost the follow-up gap it exists to demonstrate"
    )


def test_conventional_referral_no_show_is_plausible(app_state):
    """Sanity-check the behavioural model against reality.

    Published cascades imply that most people referred onward from a
    screening camp for a non-communicable disease never complete the
    referral. A model predicting 5% or 99% no-show would be useless; this
    test pins it to a defensible band and deliberately errs towards
    under-claiming the problem.
    """
    profile = app_state.barrier_profile(sample=400)
    mean_no_show = profile["mean_conventional_no_show"]
    assert 0.35 <= mean_no_show <= 0.80, (
        f"mean predicted no-show under conventional referral is "
        f"{mean_no_show:.3f}, which is outside any defensible range"
    )


def test_backlog_is_substantial_and_aged(app_state):
    """A credible starting state: thousands open, most of them overdue."""
    headline = app_state.headline()
    assert headline["care_debts_open"] > 1000
    breached_share = headline["care_debts_breached"] / headline["care_debts_open"]
    assert breached_share > 0.5, (
        "most open obligations should already be past their clinical "
        "deadline; that is the condition the project exists to address"
    )
    buckets = {row["bucket"]: row["count"] for row in app_state.aging()}
    assert buckets["Over 90 days overdue"] > 0, (
        "no obligations older than 90 days: the simulated backlog is too "
        "young to be realistic"
    )
