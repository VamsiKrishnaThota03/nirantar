"""End-to-end checks over the HTTP surface."""

from __future__ import annotations


def test_all_aggregate_views_respond(client):
    for path in (
        "/api/overview",
        "/api/cascade",
        "/api/aging",
        "/api/conditions",
        "/api/panchayats",
        "/api/supply-gaps",
        "/api/barriers",
        "/api/blocked-reasons",
        "/api/escalations/clusters",
        "/api/worklist?limit=5",
        "/api/llm/usage",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        assert response.json() is not None


def test_worklist_is_ordered_by_expected_harm(client):
    rows = client.get("/api/worklist?limit=25").json()
    assert rows
    # The most severe conditions should dominate the head of the queue.
    head = rows[0]
    assert head["severity_weight"] >= rows[-1]["severity_weight"]
    for row in rows:
        assert "person" in row
        assert row["days_to_deadline"] is not None


def test_plan_then_close_updates_the_public_impact_ledger(client):
    before = client.get("/api/ledger/summary").json()["debts_closed"]

    # Filter by condition rather than trusting a refill to appear in the
    # severity-ordered head of the queue -- it will not, by design.
    rows = client.get(
        "/api/worklist?limit=10&condition=hypertension_refill_due"
    ).json()
    assert rows, "no overdue blood-pressure refills in the generated world"
    debt_id = rows[0]["debt_id"]

    planned = client.post(f"/api/debts/{debt_id}/plan")
    assert planned.status_code == 200
    body = planned.json()
    assert body["run"]["error"] is None
    plan = body["run"]["plan"]
    assert plan is not None
    assert plan["counterfactual"]["cost_inr"] is not None

    closed = client.post(
        f"/api/debts/{debt_id}/close",
        json={
            "kind": "drug_dispensed",
            "detail": "Amlodipine 5mg x 30 dispensed at the mobile unit.",
            "recorded_by": "asha-001",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["decision"]["accepted"] is True

    after = client.get("/api/ledger/summary").json()["debts_closed"]
    assert after == before + 1
    assert client.get("/api/ledger/verify").json()["valid"] is True


def test_closing_with_the_wrong_evidence_is_refused_by_the_api(client):
    rows = client.get(
        "/api/worklist?limit=10&condition=hypertension_refill_due"
    ).json()
    assert rows
    response = client.post(
        f"/api/debts/{rows[0]['debt_id']}/close",
        json={
            "kind": "visit_logged",
            "detail": "Spoke to the patient about adherence.",
            "recorded_by": "tester",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["decision"]["accepted"] is False


def test_closing_without_an_evidence_payload_is_impossible(client):
    """There is no 'mark as done'. The schema itself forbids it."""
    rows = client.get("/api/worklist?limit=5").json()
    response = client.post(f"/api/debts/{rows[0]['debt_id']}/close", json={})
    assert response.status_code == 422


def test_batch_simulation_reports_real_aggregates(client):
    response = client.post("/api/simulate/batch", json={"limit": 60})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attempted"] > 0
    assert body["planned"] > 0
    assert body["patient_rupees_saved"] >= 0
    assert body["elapsed_seconds"] >= 0
    # Bulk planning must not have spent tokens.
    usage = client.get("/api/llm/usage").json()
    assert usage["calls"] == 0


def test_streaming_trace_emits_one_frame_per_agent(client):
    rows = client.get("/api/worklist?limit=5").json()
    debt_id = rows[0]["debt_id"]
    with client.stream("GET", f"/api/debts/{debt_id}/plan/stream") as response:
        assert response.status_code == 200
        payload = "".join(response.iter_text())
    for agent in ("Triage", "Reality", "Supply", "Planner", "Verifier"):
        assert agent in payload, f"{agent} never reported in the stream"
    assert "run_finished" in payload


def test_unknown_debt_is_a_404(client):
    assert client.get("/api/debts/d-does-not-exist").status_code == 404
    assert client.post("/api/debts/d-does-not-exist/plan").status_code == 404


def test_escalation_run_writes_briefs(client):
    response = client.post("/api/escalations/run?top=2")
    assert response.status_code == 200
    escalations = response.json()["escalations"]
    assert escalations
    for item in escalations:
        assert item["to_role"] == "Block Medical Officer"
        assert item["brief_markdown"]
    assert client.get("/api/escalations").json()


def test_calibration_endpoint_exposes_assumptions(client):
    body = client.get("/api/calibration").json()
    assert body["assumed_count"] > 0, (
        "the model has assumptions; hiding them would make it unauditable"
    )
    assert any(item["source"] != "ASSUMED" for item in body["constants"])
    assert "fictional" in body["note"]


def test_ledger_entries_are_paginated_and_privacy_safe(client):
    client.post("/api/simulate/batch", json={"limit": 20})
    body = client.get("/api/ledger/entries?limit=10").json()
    assert body["total"] >= 1
    assert len(body["entries"]) <= 10
    assert "privacy_note" in body
    for entry in body["entries"]:
        assert set(entry) >= {"seq", "entry_hash", "prev_hash", "signature"}
        assert "display_name" not in entry["payload"]
