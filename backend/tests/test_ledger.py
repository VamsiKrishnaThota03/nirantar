"""The Impact Ledger has to be worth trusting, so it is tested adversarially."""

from __future__ import annotations

import json

import pytest


def test_chain_verifies_when_untouched(app_state):
    for index in range(12):
        app_state.ledger.append(
            "debt_closed",
            person_id=f"p-{index:06d}",
            debt_id=f"d-{index:06d}",
            payload={"condition": "hypertension_suspect", "days_open": index},
        )
    report = app_state.ledger.verify()
    assert report["valid"], report["problems"]
    assert report["entries"] >= 12


def test_editing_a_payload_breaks_verification(app_state):
    """The point of the whole design: you cannot quietly improve the numbers."""
    app_state.ledger.append(
        "debt_closed",
        person_id="p-000001",
        debt_id="d-000001",
        payload={"condition": "tb_confirmed_not_initiated", "cost_to_patient_inr": 95.0},
    )
    assert app_state.ledger.verify()["valid"]

    # Tamper directly in the database, the way a motivated operator would.
    row = app_state.db.one(
        "SELECT seq, payload_json FROM ledger WHERE event_type='debt_closed' "
        "ORDER BY seq DESC LIMIT 1"
    )
    payload = json.loads(row[1])
    payload["cost_to_patient_inr"] = 1.0
    app_state.db.run(
        "UPDATE ledger SET payload_json=? WHERE seq=?",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")), row[0]),
    )

    report = app_state.ledger.verify()
    assert not report["valid"]
    assert any("digest" in problem["problem"] for problem in report["problems"])


def test_deleting_an_entry_breaks_the_chain(app_state):
    for index in range(5):
        app_state.ledger.append(
            "debt_closed",
            person_id=f"p-{index:06d}",
            debt_id=f"d-{index:06d}",
            payload={"condition": "diabetes_suspect"},
        )
    head_seq, _ = app_state.ledger.head()
    app_state.db.run("DELETE FROM ledger WHERE seq=?", (head_seq - 2,))
    report = app_state.ledger.verify()
    assert not report["valid"]


def test_forging_an_entry_without_the_key_fails(app_state):
    """An appended row with a plausible hash but no valid signature is caught."""
    import hashlib

    prev_seq, prev_hash = app_state.ledger.head()
    seq = prev_seq + 1
    payload_json = '{"condition":"invented"}'
    digest = hashlib.sha256(payload_json.encode()).hexdigest()
    app_state.db.run(
        """INSERT INTO ledger (seq, ts, event_type, subject, debt_ref,
               payload_json, payload_digest, prev_hash, entry_hash, signature, key_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            seq,
            "2026-11-10T00:00:00+00:00",
            "debt_closed",
            "forged-subject",
            "forged-debt",
            payload_json,
            digest,
            prev_hash,
            "0" * 64,
            "ab" * 32,
            app_state.ledger.key_id,
        ),
    )
    report = app_state.ledger.verify()
    assert not report["valid"]


def test_ledger_carries_no_identifying_data(app_state):
    """A public audit trail that leaks a patient's village is a harm, not a feature."""
    person = next(iter(app_state.world.people.values()))
    app_state.ledger.append(
        "debt_closed",
        person_id=person.id,
        debt_id="d-0000001",
        payload={
            "condition": "hypertension_suspect",
            # A careless caller tries to log a name and a phone number.
            "display_name": person.display_name,
            "phone": "9999999999",
            "village": person.village,
        },
    )
    entries = app_state.ledger.entries(limit=500)
    blob = json.dumps(entries)
    assert person.display_name not in blob
    assert "9999999999" not in blob
    assert person.id not in blob
    # The disallowed keys were dropped rather than stored.
    last = entries[-1]
    assert "display_name" not in last["payload"]
    assert "phone" not in last["payload"]
    assert "village" not in last["payload"]


def test_pseudonyms_are_stable_and_distinct(app_state):
    first = app_state.ledger.pseudonymise("p-000001")
    assert first == app_state.ledger.pseudonymise("p-000001")
    assert first != app_state.ledger.pseudonymise("p-000002")


def test_unknown_event_types_are_refused(app_state):
    with pytest.raises(ValueError):
        app_state.ledger.append(
            "we_did_a_great_job",
            person_id="p-000001",
            debt_id="d-1",
            payload={},
        )


def test_signing_key_is_owner_only_on_disk(app_state):
    import stat

    mode = app_state.settings.ledger_key_path.stat().st_mode
    assert not mode & stat.S_IRGRP
    assert not mode & stat.S_IROTH


def test_concurrent_readers_and_writers_do_not_corrupt_results(app_state):
    """Regression: a shared SQLite connection raced across FastAPI's threadpool.

    The symptom was not an exception from SQLite. It was ``SELECT COUNT(*)``
    returning ``None`` while a batch run wrote to the same connection, which
    crashed the public ledger endpoint. Reads and writes are now serialised,
    so this hammers both at once and insists every read is well-formed.
    """
    import threading

    errors: list[str] = []

    def writer() -> None:
        try:
            for index in range(40):
                app_state.ledger.append(
                    "debt_closed",
                    person_id=f"p-{index:06d}",
                    debt_id=f"d-{index:06d}",
                    payload={"condition": "hypertension_suspect"},
                )
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(f"writer: {type(exc).__name__}: {exc}")

    def reader() -> None:
        try:
            for _ in range(60):
                count = app_state.ledger.count()
                assert isinstance(count, int)
                impact = app_state.ledger.impact()
                assert isinstance(impact["ledger_entries"], int)
                app_state.ledger.entries(limit=5)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reader: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer) for _ in range(2)] + [
        threading.Thread(target=reader) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    # The chain must still be intact and sequential after concurrent appends.
    report = app_state.ledger.verify()
    assert report["valid"], report["problems"]
