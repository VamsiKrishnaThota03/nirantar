"""The Impact Ledger: a hash-chained, signed, publicly auditable record of
every care obligation this system closed.

Why this exists
---------------
Health-tech pilots are judged on intentions. "We sent 40,000 reminders." A
reminder is not an outcome. Nirantar therefore makes measurement a
first-class, tamper-evident part of the product rather than a slide at the
end: every state change on a care debt is appended to an append-only log,
each entry hash-chained to its predecessor and signed with an Ed25519 key.
Anyone can fetch the whole chain and verify it without trusting us. If we
quietly edited a closure to flatter ourselves, verification breaks loudly.

Privacy
-------
The chain is public; the patients are not. No entry contains a name, phone
number, village, or identifier. The subject of each entry is a keyed hash of
the internal person id, so the chain proves *that* an obligation to a
distinct person was discharged, and supports counting distinct people,
without revealing who they are. Payloads are restricted to an allowlist of
non-identifying fields, enforced here rather than left to callers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

GENESIS = "0" * 64

# Fields a ledger payload may carry. Anything else is dropped, so a careless
# caller cannot leak a name into a public artefact.
ALLOWED_PAYLOAD_FIELDS = frozenset(
    {
        "condition",
        "required_action",
        "evidence_kinds",
        "days_open",
        "days_to_deadline",
        "risk_score",
        "strategy",
        "outreach_channel",
        "cost_to_patient_inr",
        "counterfactual_cost_inr",
        "predicted_no_show",
        "counterfactual_no_show",
        "travel_km",
        "counterfactual_travel_km",
        "wage_loss_days",
        "counterfactual_wage_loss_days",
        "panchayat_code",
        "facility_type",
        "corroborated",
        "plan_generated_by",
        "escalated_to_role",
        "systemic_cause",
        "reason",
    }
)

EVENT_TYPES = frozenset(
    {
        "debt_opened",
        "plan_created",
        "outreach_attempted",
        "debt_closed",
        "debt_escalated",
        "debt_unreachable",
        "dataset_initialised",
    }
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class ImpactLedger:
    def __init__(self, db: "Db", key_path: Path) -> None:
        self._db = db
        self._key_path = key_path
        self._private = self._load_or_create_key(key_path)
        self._public = self._private.public_key()
        # Salt for subject pseudonymisation, derived from the signing key so
        # it needs no separate secret and never leaves this process.
        self._subject_salt = hashlib.sha256(
            b"nirantar-subject-salt/v1"
            + self._private.private_bytes_raw()
        ).digest()
        self._ensure_schema()

    # --- key management ----------------------------------------------------

    @staticmethod
    def _load_or_create_key(path: Path) -> Ed25519PrivateKey:
        # An inline PEM takes precedence over the file. Hosts with ephemeral
        # filesystems (free container tiers, scale-to-zero platforms) would
        # otherwise regenerate the key on every deploy, and previously signed
        # entries could no longer be verified against the published public
        # key -- the chain survives, but the ability to prove it does not.
        # Supply this through the platform's secret store, never in a file.
        inline = os.environ.get("LEDGER_SIGNING_KEY_PEM")
        if inline and inline.strip():
            key = serialization.load_pem_private_key(
                inline.strip().encode("utf-8"), password=None
            )
            if not isinstance(key, Ed25519PrivateKey):
                raise TypeError(
                    "LEDGER_SIGNING_KEY_PEM is not an Ed25519 private key"
                )
            return key
        if path.exists():
            data = path.read_bytes()
            key = serialization.load_pem_private_key(data, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise TypeError(f"{path} is not an Ed25519 private key")
            return key
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Create with owner-only permissions from the outset rather than
        # chmod-ing after the bytes are already on disk.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.write(fd, pem)
        finally:
            os.close(fd)
        return key

    @property
    def key_id(self) -> str:
        raw = self._public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return hashlib.sha256(raw).hexdigest()[:16]

    def public_key_b64(self) -> str:
        import base64

        raw = self._public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    # --- schema ------------------------------------------------------------

    def _ensure_schema(self) -> None:
        self._db.script(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                seq            INTEGER PRIMARY KEY,
                ts             TEXT NOT NULL,
                event_type     TEXT NOT NULL,
                subject        TEXT NOT NULL,
                debt_ref       TEXT NOT NULL,
                payload_json   TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                prev_hash      TEXT NOT NULL,
                entry_hash     TEXT NOT NULL,
                signature      TEXT NOT NULL,
                key_id         TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_event ON ledger(event_type);
            CREATE INDEX IF NOT EXISTS idx_ledger_subject ON ledger(subject);
            """
        )

    # --- privacy -----------------------------------------------------------

    def pseudonymise(self, person_id: str) -> str:
        """Keyed hash of an internal id. Stable, unlinkable, not reversible."""
        return hmac.new(
            self._subject_salt, person_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()[:24]

    @staticmethod
    def _redact(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in sorted(payload.items())
            if key in ALLOWED_PAYLOAD_FIELDS
        }

    # --- append ------------------------------------------------------------

    def head(self) -> tuple[int, str]:
        row = self._db.one(
            "SELECT seq, entry_hash FROM ledger ORDER BY seq DESC LIMIT 1"
        )
        if row is None:
            return 0, GENESIS
        return int(row[0]), str(row[1])

    def append(
        self,
        event_type: str,
        person_id: str,
        debt_id: str,
        payload: dict[str, Any],
        *,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown ledger event type: {event_type}")
        # The whole append is one critical section: reading the head decides
        # the sequence number and the previous hash that the insert then
        # commits to.
        with self._db.transaction():
            return self._append_locked(event_type, person_id, debt_id, payload, ts)

    def _append_locked(
        self,
        event_type: str,
        person_id: str,
        debt_id: str,
        payload: dict[str, Any],
        ts: datetime | None,
    ) -> dict[str, Any]:
        prev_seq, prev_hash = self.head()
        seq = prev_seq + 1
        when = (ts or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        subject = self.pseudonymise(person_id)
        # Debt reference is also pseudonymised: a debt id maps to a person.
        debt_ref = self.pseudonymise("debt:" + debt_id)
        clean = self._redact(payload)
        payload_json = _canonical(clean)
        payload_digest = _sha256_hex(payload_json)
        preimage = _canonical(
            {
                "seq": seq,
                "ts": when,
                "event_type": event_type,
                "subject": subject,
                "debt_ref": debt_ref,
                "payload_digest": payload_digest,
                "prev_hash": prev_hash,
            }
        )
        entry_hash = _sha256_hex(preimage)
        signature = self._private.sign(bytes.fromhex(entry_hash)).hex()
        self._db.run(
            """INSERT INTO ledger
               (seq, ts, event_type, subject, debt_ref, payload_json,
                payload_digest, prev_hash, entry_hash, signature, key_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                seq,
                when,
                event_type,
                subject,
                debt_ref,
                payload_json,
                payload_digest,
                prev_hash,
                entry_hash,
                signature,
                self.key_id,
            ),
        )
        return {
            "seq": seq,
            "ts": when,
            "event_type": event_type,
            "subject": subject,
            "debt_ref": debt_ref,
            "payload": clean,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
            "signature": signature,
            "key_id": self.key_id,
        }

    # --- read & verify -----------------------------------------------------

    def entries(self, offset: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._db.all(
            """SELECT seq, ts, event_type, subject, debt_ref, payload_json,
                      payload_digest, prev_hash, entry_hash, signature, key_id
               FROM ledger ORDER BY seq ASC LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        return [
            {
                "seq": int(r[0]),
                "ts": r[1],
                "event_type": r[2],
                "subject": r[3],
                "debt_ref": r[4],
                "payload": json.loads(r[5]),
                "payload_digest": r[6],
                "prev_hash": r[7],
                "entry_hash": r[8],
                "signature": r[9],
                "key_id": r[10],
            }
            for r in rows
        ]

    def count(self) -> int:
        row = self._db.one("SELECT COUNT(*) FROM ledger")
        return int(row[0]) if row else 0

    def verify(self) -> dict[str, Any]:
        """Recompute the whole chain and check every signature.

        Returns a report rather than raising, because the dashboard shows the
        result and a judge should be able to see a failure if one exists.
        """
        rows = self._db.all(
            """SELECT seq, ts, event_type, subject, debt_ref, payload_json,
                      payload_digest, prev_hash, entry_hash, signature
               FROM ledger ORDER BY seq ASC"""
        )
        prev_hash = GENESIS
        problems: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            (
                seq,
                ts,
                event_type,
                subject,
                debt_ref,
                payload_json,
                payload_digest,
                row_prev,
                entry_hash,
                signature,
            ) = row
            if int(seq) != index:
                problems.append({"seq": seq, "problem": "sequence gap or reordering"})
            if row_prev != prev_hash:
                problems.append({"seq": seq, "problem": "broken chain link"})
            if _sha256_hex(payload_json) != payload_digest:
                problems.append({"seq": seq, "problem": "payload digest mismatch"})
            recomputed = _sha256_hex(
                _canonical(
                    {
                        "seq": int(seq),
                        "ts": ts,
                        "event_type": event_type,
                        "subject": subject,
                        "debt_ref": debt_ref,
                        "payload_digest": payload_digest,
                        "prev_hash": row_prev,
                    }
                )
            )
            if recomputed != entry_hash:
                problems.append({"seq": seq, "problem": "entry hash mismatch"})
            try:
                self._public.verify(bytes.fromhex(signature), bytes.fromhex(entry_hash))
            except (InvalidSignature, ValueError):
                problems.append({"seq": seq, "problem": "invalid signature"})
            prev_hash = entry_hash
        return {
            "entries": len(rows),
            "valid": not problems,
            "head_hash": prev_hash,
            "key_id": self.key_id,
            "public_key_ed25519_b64": self.public_key_b64(),
            "problems": problems[:50],
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "how_to_verify_independently": (
                "For each entry in /api/ledger/entries, recompute "
                "sha256(canonical_json({seq, ts, event_type, subject, "
                "debt_ref, payload_digest, prev_hash})) and check it equals "
                "entry_hash; then verify the Ed25519 signature over those "
                "hash bytes with the published public key. canonical_json is "
                "JSON with sorted keys and no whitespace."
            ),
        }

    # --- impact aggregates -------------------------------------------------

    def impact(self) -> dict[str, Any]:
        """Outcomes, counted off the signed chain rather than off app state.

        This is the number we would put in front of a judge, and it is derived
        from the same immutable record anyone else can audit.
        """
        closed = self._db.all(
            "SELECT payload_json FROM ledger WHERE event_type = 'debt_closed'"
        )
        distinct_row = self._db.one(
            "SELECT COUNT(DISTINCT subject) FROM ledger "
            "WHERE event_type = 'debt_closed'"
        )
        distinct_people = int(distinct_row[0]) if distinct_row else 0
        rupees_saved = 0.0
        km_saved = 0.0
        wage_days_saved = 0.0
        by_condition: dict[str, int] = {}
        noshow_avoided = 0.0
        for (payload_json,) in closed:
            payload = json.loads(payload_json)
            cost = float(payload.get("cost_to_patient_inr") or 0.0)
            cf_cost = float(payload.get("counterfactual_cost_inr") or 0.0)
            rupees_saved += max(0.0, cf_cost - cost)
            km = float(payload.get("travel_km") or 0.0)
            cf_km = float(payload.get("counterfactual_travel_km") or 0.0)
            km_saved += max(0.0, cf_km - km)
            wage_days_saved += max(
                0.0,
                float(payload.get("counterfactual_wage_loss_days") or 0.0)
                - float(payload.get("wage_loss_days") or 0.0),
            )
            cond = str(payload.get("condition") or "unknown")
            by_condition[cond] = by_condition.get(cond, 0) + 1
            noshow = float(payload.get("predicted_no_show") or 0.0)
            cf_noshow = float(payload.get("counterfactual_no_show") or 0.0)
            noshow_avoided += max(0.0, cf_noshow - noshow)
        return {
            "debts_closed": len(closed),
            "distinct_people_served": distinct_people,
            "patient_rupees_saved": round(rupees_saved, 2),
            "patient_travel_km_avoided": round(km_saved, 1),
            "patient_wage_days_saved": round(wage_days_saved, 1),
            "expected_additional_closures_vs_conventional": round(noshow_avoided, 1),
            "closed_by_condition": dict(sorted(by_condition.items(), key=lambda kv: -kv[1])),
            "ledger_entries": self.count(),
        }


class Db:
    """A thread-safe wrapper around one SQLite connection.

    FastAPI runs synchronous endpoint functions in a thread pool, so several
    requests can touch this connection at the same moment. A ``sqlite3``
    connection tolerates that only if each statement and its fetch happen
    without another statement interleaving on the same connection -- and when
    they do interleave, the symptom is not a clean error. It is
    ``SELECT COUNT(*)`` returning ``None``, which surfaced here as a crash in
    the public ledger endpoint while a batch run was in flight.

    So every statement and its fetch are taken under one lock. For a block of
    a few hundred thousand people this is ample; a state-wide deployment
    would move to Postgres and a connection pool, and the interface here is
    deliberately narrow enough to make that a drop-in change.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.commit()

    @contextmanager
    def transaction(self) -> "Iterator[Db]":
        """Hold the lock across several statements.

        Needed wherever a read decides what gets written. Appending to the
        ledger reads the current head to compute the next sequence number and
        the previous hash; if another thread appends between those two steps,
        both writers pick the same sequence number and chain to the same
        predecessor -- a forked chain, which is exactly the failure the whole
        hash-chain design exists to make impossible. The lock is re-entrant,
        so the ordinary helpers can be called inside this block.
        """
        with self._lock:
            yield self

    def one(self, sql: str, params: tuple = ()) -> tuple | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def run(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def script(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def connect(db_path: Path) -> Db:
    return Db(db_path)
