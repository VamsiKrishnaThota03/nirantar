"""Exercises the language-model path without spending tokens.

The deterministic core is covered elsewhere. These tests cover the branch
that only runs when ANTHROPIC_API_KEY is set, because otherwise the most
security- and safety-relevant code in the project -- the guardrails that
clamp what the model is allowed to change -- would ship unexercised.

A mocked HTTP transport stands in for the API, so the real request shape,
response parsing, failure handling and every bound are all tested.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from nirantar import config, llm
from nirantar.agents import planner, triage
from nirantar.agents.base import AgentContext
from nirantar.agents.orchestrator import worklist


def _reply(payload: dict, *, input_tokens: int = 120, output_tokens: int = 60) -> dict:
    """A well-formed Anthropic Messages API response body."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


@pytest.fixture
def with_mock_api(monkeypatch):
    """Point the client at a mock transport and capture outbound requests."""
    # Deliberately not shaped like a real Anthropic key: the client only
    # checks that the variable is non-empty, and a realistic-looking literal
    # trips secret scanners for no benefit.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-placeholder")
    config.reset_settings_for_tests()

    state: dict = {"requests": [], "responses": [], "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(json.loads(request.content))
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": "nope"})
        body = state["responses"].pop(0) if state["responses"] else _reply({})
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    # Reset the usage counters so assertions are about this test only.
    llm.USAGE.calls = 0
    llm.USAGE.failures = 0
    llm.USAGE.fallbacks = 0
    llm.USAGE._window_calls = 0
    yield state
    config.reset_settings_for_tests()


# --- the client ------------------------------------------------------------


def test_request_shape_matches_the_messages_api(with_mock_api):
    with_mock_api["responses"] = [_reply({"ok": True})]
    result = asyncio.run(llm.complete_json(system="S", prompt="P", max_tokens=99))
    assert result == {"ok": True}
    sent = with_mock_api["requests"][0]
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["max_tokens"] == 99
    assert sent["system"] == "S"
    assert sent["messages"] == [{"role": "user", "content": "P"}]
    assert llm.USAGE.calls == 1
    assert llm.USAGE.input_tokens >= 120


def test_fenced_json_is_parsed(with_mock_api):
    with_mock_api["responses"] = [
        {
            "content": [
                {"type": "text", "text": '```json\n{"adjustment": 3}\n```'}
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    ]
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) == {"adjustment": 3}


def test_prose_wrapped_json_is_recovered(with_mock_api):
    with_mock_api["responses"] = [
        {
            "content": [
                {
                    "type": "text",
                    "text": 'Here is my answer:\n{"adjustment": 2}\nHope that helps.',
                }
            ],
            "usage": {},
        }
    ]
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) == {"adjustment": 2}


def test_unparseable_response_falls_back_to_none(with_mock_api):
    with_mock_api["responses"] = [
        {"content": [{"type": "text", "text": "I would rather not."}], "usage": {}},
        {"content": [{"type": "text", "text": "Still no."}], "usage": {}},
    ]
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) is None
    assert llm.USAGE.fallbacks >= 1


def test_auth_failure_does_not_retry_and_falls_back(with_mock_api):
    with_mock_api["status"] = 401
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) is None
    # A credentials problem is not transient; retrying would just burn time.
    assert len(with_mock_api["requests"]) == 1
    assert llm.USAGE.failures == 1


def test_hourly_budget_stops_calling(with_mock_api, monkeypatch):
    monkeypatch.setenv("LLM_MAX_CALLS_PER_HOUR", "2")
    config.reset_settings_for_tests()
    with_mock_api["responses"] = [_reply({"a": 1}), _reply({"a": 2}), _reply({"a": 3})]
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) is not None
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) is not None
    # Third call is refused locally rather than sent.
    assert asyncio.run(llm.complete_json(system="S", prompt="P")) is None
    assert len(with_mock_api["requests"]) == 2


def test_force_deterministic_skips_the_api_entirely(with_mock_api):
    token = llm.FORCE_DETERMINISTIC.set(True)
    try:
        assert asyncio.run(llm.complete_json(system="S", prompt="P")) is None
    finally:
        llm.FORCE_DETERMINISTIC.reset(token)
    assert with_mock_api["requests"] == []


# --- the guardrails --------------------------------------------------------


def _ctx(app_state):
    return AgentContext(
        world=app_state.world, ledger=app_state.ledger, as_of=app_state.as_of
    )


def test_triage_clamps_an_out_of_range_adjustment(app_state, with_mock_api):
    with_mock_api["responses"] = [
        _reply({"adjustment": 500, "rationale": "Very urgent.", "clinical_flags": ["x"]})
    ]
    debt = next(
        d
        for d in app_state.world.open_debts()
        if d.condition == "hypertension_suspect"
    )
    ctx = _ctx(app_state)
    base, _ = triage.deterministic_score(ctx, debt)
    asyncio.run(triage.run(ctx, debt))
    assert debt.risk_score <= min(100.0, base + triage.MAX_LLM_ADJUSTMENT)
    overrides = ctx.shared["triage"]["safety_overrides"]
    assert any("clamped" in note for note in overrides)


def test_triage_refuses_to_deprioritise_a_critical_case(app_state, with_mock_api):
    """The model may escalate a confirmed TB case. It may not bury one."""
    with_mock_api["responses"] = [
        _reply({"adjustment": -12, "rationale": "Looks fine.", "clinical_flags": []})
    ]
    debt = next(
        d
        for d in app_state.world.open_debts()
        if d.condition == "tb_confirmed_not_initiated"
    )
    ctx = _ctx(app_state)
    base, _ = triage.deterministic_score(ctx, debt)
    asyncio.run(triage.run(ctx, debt))
    assert debt.risk_score >= base
    assert any(
        "critical list" in note
        for note in ctx.shared["triage"]["safety_overrides"]
    )


def test_triage_rationale_is_length_bounded(app_state, with_mock_api):
    with_mock_api["responses"] = [
        _reply({"adjustment": 0, "rationale": "x" * 5000, "clinical_flags": []})
    ]
    debt = next(iter(app_state.world.open_debts()))
    ctx = _ctx(app_state)
    asyncio.run(triage.run(ctx, debt))
    assert len(debt.risk_rationale) <= 300


def test_planner_refuses_a_plan_that_is_not_on_the_shortlist(app_state, with_mock_api):
    """The model chooses from the shortlist or not at all."""
    # Filter by condition: the worklist is severity-ordered, so a refill
    # never appears in its head.
    candidates = worklist(
        app_state.world,
        app_state.as_of,
        limit=20,
        condition="hypertension_refill_due",
    )
    assert candidates, "no overdue blood-pressure refills in this world"
    debt = candidates[0]
    ctx = _ctx(app_state)
    # Triage and Reality run without the model so the shortlist is stable.
    token = llm.FORCE_DETERMINISTIC.set(True)
    try:
        asyncio.run(triage.run(ctx, debt))
        from nirantar.agents import reality, supply

        asyncio.run(reality.run(ctx, debt))
        asyncio.run(supply.run(ctx, debt))
    finally:
        llm.FORCE_DETERMINISTIC.reset(token)

    shortlist = planner.shortlist(ctx, debt)
    if len(shortlist) < 2:
        pytest.skip("need a shortlist of at least two to test the bound")

    with_mock_api["responses"] = [
        _reply(
            {
                "chosen_index": 99,
                "rationale": "I pick the imaginary one.",
                "escort_recommended": True,
            }
        )
    ]
    plan = asyncio.run(planner.run(ctx, debt))
    assert plan is not None
    assert plan.generated_by == "llm"
    assert any("not on the" in note for note in plan.safety_overrides)
    # It fell back to the optimiser's own first choice.
    assert plan.strategy == shortlist[0]["label"]


def test_planner_handles_a_non_numeric_index(app_state, with_mock_api):
    # Filter by condition: the worklist is severity-ordered, so a refill
    # never appears in its head.
    candidates = worklist(
        app_state.world,
        app_state.as_of,
        limit=20,
        condition="hypertension_refill_due",
    )
    assert candidates, "no overdue blood-pressure refills in this world"
    debt = candidates[0]
    ctx = _ctx(app_state)
    token = llm.FORCE_DETERMINISTIC.set(True)
    try:
        from nirantar.agents import reality, supply

        asyncio.run(triage.run(ctx, debt))
        asyncio.run(reality.run(ctx, debt))
        asyncio.run(supply.run(ctx, debt))
    finally:
        llm.FORCE_DETERMINISTIC.reset(token)
    if len(planner.shortlist(ctx, debt)) < 2:
        pytest.skip("need a shortlist of at least two")

    with_mock_api["responses"] = [
        _reply({"chosen_index": "the cheap one", "rationale": "ok"})
    ]
    plan = asyncio.run(planner.run(ctx, debt))
    assert plan is not None
    assert any("non-integer" in note for note in plan.safety_overrides)


def test_a_model_outage_mid_pipeline_still_produces_a_complete_plan(
    app_state, with_mock_api
):
    """The whole premise of the deterministic cores, asserted."""
    from nirantar.agents import orchestrator

    with_mock_api["status"] = 500
    debt = worklist(app_state.world, app_state.as_of, limit=10)[0]
    ctx = _ctx(app_state)
    run = asyncio.run(orchestrator.plan_one(ctx, debt))
    assert run.error is None
    assert run.plan is not None
    assert run.plan.generated_by == "deterministic"
    assert run.plan.steps
    assert run.plan.artifacts["voice_script"]["script"]
