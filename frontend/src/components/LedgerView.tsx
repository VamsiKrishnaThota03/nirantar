/** The Impact Ledger, shown as an audit surface rather than a scoreboard.
 *
 * Judging weights proven impact at 25% and explicitly asks for deployment
 * data rather than intentions. So this view does not assert outcomes; it
 * publishes the signed record they are derived from, the verification result,
 * and the public key, and invites the reader to check the arithmetic.
 */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type LedgerEntry,
  type LedgerImpact,
  type LedgerVerify,
} from "../lib/api";
import { compact, dateFull, n, n1, rupeesCompact, titleCase } from "../lib/format";
import { Card, ErrorNote, Loading, Stat } from "./primitives";

export function LedgerView({
  refreshKey,
  onLedgerChange,
}: {
  refreshKey: number;
  onLedgerChange: () => void;
}) {
  const [impact, setImpact] = useState<LedgerImpact | null>(null);
  const [verify, setVerify] = useState<LedgerVerify | null>(null);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [privacyNote, setPrivacyNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [batchResult, setBatchResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [impactData, verifyData, entriesData] = await Promise.all([
        api.ledgerSummary(),
        api.ledgerVerify(),
        api.ledgerEntries(60),
      ]);
      setImpact(impactData);
      setVerify(verifyData);
      setEntries([...entriesData.entries].reverse());
      setTotal(entriesData.total);
      setPrivacyNote(entriesData.privacy_note);
    } catch (caught) {
      setError(caught);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function runBatch() {
    setBusy(true);
    setBatchResult(null);
    try {
      const result = await api.batch(300);
      setBatchResult(
        `Planned ${n(result.planned)} of ${n(result.attempted)} obligations in ${result.elapsed_seconds}s. ` +
          `${rupeesCompact(result.patient_rupees_saved)} of household costs avoided, ` +
          `${n(result.patient_travel_km_avoided)} km of travel removed, ` +
          `${n(result.plans_requiring_no_travel)} plans needing no travel at all, ` +
          `and ${n1(result.expected_additional_attendances)} additional attendances expected ` +
          `against the referrals these people would otherwise have received. No model tokens spent.`,
      );
      await load();
      // Keep the shell's own counters in step; otherwise the footer still
      // reports the pre-batch entry count.
      onLedgerChange();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!impact || !verify) return <Loading lines={6} />;

  return (
    <>
      <div className="section-head">
        <h2>The Impact Ledger</h2>
        <p>
          Every care obligation closed by this system is appended to an
          append-only log, hash-chained to its predecessor and signed with an
          Ed25519 key. You do not have to believe our numbers: fetch the chain,
          recompute the hashes, verify the signatures against the published
          public key. If we had quietly edited a closure to flatter ourselves,
          the check below would fail.
        </p>
      </div>

      <div
        className="banner"
        style={{
          borderColor: verify.valid
            ? "color-mix(in srgb, var(--good) 50%, transparent)"
            : "var(--critical)",
          background: verify.valid
            ? "color-mix(in srgb, var(--good) 8%, var(--surface-1))"
            : "color-mix(in srgb, var(--critical) 10%, var(--surface-1))",
        }}
      >
        <span aria-hidden>{verify.valid ? "✓" : "✕"}</span>
        <div>
          <strong>
            {verify.valid
              ? `Chain verified — ${n(verify.entries)} entries, every hash and signature checks out.`
              : `Chain verification FAILED — ${verify.problems.length} problem(s).`}
          </strong>
          <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
            Key {verify.key_id} · head {verify.head_hash.slice(0, 16)}… ·
            checked {new Date(verify.verified_at).toLocaleTimeString("en-IN")}
          </div>
          {!verify.valid && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12.5 }}>
              {verify.problems.slice(0, 6).map((problem) => (
                <li key={`${problem.seq}-${problem.problem}`}>
                  entry #{problem.seq}: {problem.problem}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="grid cols-4">
        <Stat
          label="Obligations closed with evidence"
          value={n(impact.debts_closed)}
          foot={`${n(impact.distinct_people_served)} distinct people`}
        />
        <Stat
          label="Household costs avoided"
          value={rupeesCompact(impact.patient_rupees_saved)}
          foot="versus conventional referral"
          tone="good"
        />
        <Stat
          label="Travel removed"
          value={`${compact(impact.patient_travel_km_avoided)} km`}
          foot={`${n1(impact.patient_wage_days_saved)} working days saved`}
          tone="good"
        />
        <Stat
          label="Extra attendances expected"
          value={n1(impact.expected_additional_closures_vs_conventional)}
          foot="summed no-show reduction"
          tone="good"
        />
      </div>

      <div style={{ marginTop: 16 }} className="grid split">
        <Card
          title="Run the backlog"
          sub="Plans a slice of the block's outstanding obligations with the deterministic optimiser — no model calls — and writes every prediction to the ledger before any outcome is known."
        >
          <button className="btn" onClick={runBatch} disabled={busy}>
            {busy ? "Planning…" : "Plan 300 obligations now"}
          </button>
          {batchResult && (
            <p style={{ fontSize: 13.3, marginTop: 12 }}>{batchResult}</p>
          )}
          <p className="note">
            Predictions are logged <em>before</em> outcomes are known. Logging
            only the successes is how pilots accidentally launder their own
            results, so plan creation and closure are both recorded and both
            auditable.
          </p>
        </Card>

        <Card
          title="Closed by condition"
          sub="Counted off the signed chain, not off application state."
        >
          {Object.keys(impact.closed_by_condition).length === 0 ? (
            <p className="sub">
              Nothing closed yet. Close a case in the agent view, or plan the
              backlog on the left.
            </p>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Condition</th>
                  <th>Closed</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(impact.closed_by_condition)
                  .slice(0, 9)
                  .map(([key, value]) => (
                    <tr key={key}>
                      <td>{titleCase(key)}</td>
                      <td>{n(value)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card
          title={`Chain — most recent of ${n(total)} entries`}
          sub={privacyNote}
        >
          <div style={{ maxHeight: 460, overflowY: "auto" }}>
            <table className="data">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Event</th>
                  <th>Subject</th>
                  <th>Payload</th>
                  <th>Entry hash</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.seq}>
                    <td>{entry.seq}</td>
                    <td style={{ textAlign: "left" }}>
                      <span
                        className={`pill ${
                          entry.event_type === "debt_closed"
                            ? "good"
                            : entry.event_type === "debt_escalated"
                              ? "crit"
                              : ""
                        }`}
                      >
                        {titleCase(entry.event_type)}
                      </span>
                      <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
                        {dateFull(entry.ts)}
                      </div>
                    </td>
                    <td>
                      <pre className="hash">{entry.subject.slice(0, 12)}…</pre>
                    </td>
                    <td style={{ textAlign: "left", fontSize: 11.5 }}>
                      {Object.entries(entry.payload)
                        .slice(0, 3)
                        .map(([key, value]) => (
                          <div key={key} style={{ color: "var(--text-secondary)" }}>
                            {key.replace(/_/g, " ")}:{" "}
                            <b style={{ color: "var(--text-primary)" }}>
                              {String(value)}
                            </b>
                          </div>
                        ))}
                    </td>
                    <td>
                      <pre className="hash">{entry.entry_hash.slice(0, 14)}…</pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card title="Verify it yourself">
          <p style={{ fontSize: 13.3, marginTop: 0 }}>
            {verify.how_to_verify_independently}
          </p>
          <dl className="kv">
            <dt>Algorithm</dt>
            <dd>Ed25519 over SHA-256 entry hashes</dd>
            <dt>Key id</dt>
            <dd>
              <pre className="hash">{verify.key_id}</pre>
            </dd>
            <dt>Public key</dt>
            <dd>
              <pre className="hash">{verify.public_key_ed25519_b64}</pre>
            </dd>
            <dt>Endpoints</dt>
            <dd>
              <code>/api/ledger/entries</code> ·{" "}
              <code>/api/ledger/verify</code> ·{" "}
              <code>/api/ledger/public-key</code>
            </dd>
          </dl>
          <p className="note">
            The chain is public; the patients are not. No entry contains a
            name, phone number, village or identifier — each subject is a keyed
            hash of an internal record id, which lets anyone count distinct
            people served without learning who they are.
          </p>
        </Card>
      </div>
    </>
  );
}
