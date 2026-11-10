/** The ASHA field app — the view for the person who actually does the work.
 *
 * A district dashboard is for someone with a laptop and a desk. The
 * Accredited Social Health Activist has neither. She covers about a
 * thousand people, is paid per completed task, and is reading this on a
 * sub-₹8,000 handset over a connection that drops. So this surface is built
 * to different rules from the rest of the dashboard:
 *
 * * **Offline first.** Tasks are cached in local storage on load. Evidence
 *   submitted without a connection is queued and flushed when one returns.
 *   Nothing is lost and nothing blocks on the network.
 * * **One task per screen, big targets.** Not a table. She is standing in a
 *   courtyard, not sitting at a desk.
 * * **The evidence bar is on the card.** She can see exactly what will close
 *   the task before she walks over, so the trip is not wasted.
 * * **Payload size is shown.** It is the constraint that decides whether any
 *   of this works, so it stays visible rather than becoming someone's later
 *   problem.
 */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AshaObligation,
  type AshaRow,
  type AshaTaskPayload,
  type AshaVisit,
} from "../lib/api";
import { n, overdueLabel } from "../lib/format";
import { Card, ErrorNote, Loading } from "./primitives";

const CACHE_KEY = "nirantar-field-cache";
const QUEUE_KEY = "nirantar-field-queue";

type QueuedEvidence = {
  debt_id: string;
  kind: string;
  detail: string;
  recorded_by: string;
  queued_at: string;
};

function readQueue(): QueuedEvidence[] {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function writeQueue(queue: QueuedEvidence[]): void {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
}

export function FieldView({ onLedgerChange }: { onLedgerChange: () => void }) {
  const [ashas, setAshas] = useState<AshaRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [payload, setPayload] = useState<AshaTaskPayload | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [queue, setQueue] = useState<QueuedEvidence[]>(readQueue);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [flushing, setFlushing] = useState(false);
  const [fromCache, setFromCache] = useState(false);

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const rows = await api.ashas();
        setAshas(rows);
        setSelected((current) => current ?? rows[0]?.id ?? null);
      } catch (caught) {
        setError(caught);
      }
    })();
  }, []);

  const loadTasks = useCallback(async (ashaId: string) => {
    setFromCache(false);
    try {
      const data = await api.ashaTasks(ashaId);
      setPayload(data);
      localStorage.setItem(
        `${CACHE_KEY}:${ashaId}`,
        JSON.stringify({ data, at: new Date().toISOString() }),
      );
    } catch (caught) {
      // Offline, or the server is unreachable. Fall back to the cache
      // rather than showing an error: a health worker standing in a
      // courtyard needs the list, not an explanation.
      const cached = localStorage.getItem(`${CACHE_KEY}:${ashaId}`);
      if (cached) {
        setPayload(JSON.parse(cached).data);
        setFromCache(true);
      } else {
        setError(caught);
      }
    }
  }, []);

  useEffect(() => {
    if (selected) void loadTasks(selected);
  }, [selected, loadTasks]);

  const flush = useCallback(async () => {
    const pending = readQueue();
    if (pending.length === 0 || !navigator.onLine) return;
    setFlushing(true);
    const remaining: QueuedEvidence[] = [];
    for (const item of pending) {
      try {
        await api.closeDebt(item.debt_id, {
          kind: item.kind,
          detail: item.detail,
          recorded_by: item.recorded_by,
        });
      } catch (caught) {
        // 409 means it was already closed — drop it. Anything else stays
        // queued for the next attempt.
        const status = (caught as { status?: number }).status;
        if (status !== 409 && status !== 422) remaining.push(item);
      }
    }
    writeQueue(remaining);
    setQueue(remaining);
    setFlushing(false);
    onLedgerChange();
    if (selected) void loadTasks(selected);
  }, [onLedgerChange, selected, loadTasks]);

  useEffect(() => {
    if (online) void flush();
  }, [online, flush]);

  function recordDone(visit: AshaVisit, obligation: AshaObligation) {
    const item: QueuedEvidence = {
      debt_id: obligation.debt_id,
      kind: obligation.closes_with,
      detail: `Recorded in the field by ${payload?.asha.display_name ?? "ASHA"} at ${visit.village}.`,
      recorded_by: payload?.asha.id ?? "asha",
      queued_at: new Date().toISOString(),
    };
    const next = [...readQueue(), item];
    writeQueue(next);
    setQueue(next);
    setDone((current) => new Set(current).add(obligation.debt_id));
    if (navigator.onLine) void flush();
  }

  if (error) return <ErrorNote error={error} />;
  if (!ashas) return <Loading lines={5} />;

  const asha = ashas.find((row) => row.id === selected);

  return (
    <>
      <div className="section-head">
        <h2>The field app</h2>
        <p>
          The dashboard is for a district officer. This is for the Accredited
          Social Health Activist who actually walks to the house — one
          household per card, big targets, and it keeps working when the
          connection does not. Try switching your network off and marking
          something done: it queues on the handset and syncs when a signal
          returns.
        </p>
      </div>

      <div className="row" style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 13 }}>
          Health worker{" "}
          <select
            className="icon-btn"
            value={selected ?? ""}
            onChange={(event) => {
              setSelected(event.target.value);
              setDone(new Set());
            }}
          >
            {ashas.slice(0, 20).map((row) => (
              <option key={row.id} value={row.id}>
                {row.display_name} — {row.panchayat} (
                {row.obligations_in_her_villages} owed)
              </option>
            ))}
          </select>
        </label>
        <span className={`pill ${online ? "good" : "crit"}`}>
          {online ? "● online" : "○ offline"}
        </span>
        {queue.length > 0 && (
          <span className="pill warn">
            {flushing ? "syncing…" : `${queue.length} queued locally`}
          </span>
        )}
        {fromCache && <span className="pill">showing cached list</span>}
      </div>

      {asha && (
        <div className="grid cols-4" style={{ marginBottom: 16 }}>
          <div className="card stat">
            <div className="label">Covers</div>
            <div className="value sm">{asha.villages.length} villages</div>
            <div className="foot">{asha.villages.join(", ")}</div>
          </div>
          <div className="card stat">
            <div className="label">Owed care in her villages</div>
            <div className="value sm">{n(asha.obligations_in_her_villages)}</div>
            <div className="foot">obligations still open</div>
          </div>
          <div className="card stat">
            <div className="label">Her workload this week</div>
            <div className="value sm">
              {asha.open_tasks} / {asha.weekly_visit_capacity}
            </div>
            <div className="foot">
              {asha.open_tasks >= asha.weekly_visit_capacity
                ? "at capacity — the planner stops assigning her escorts"
                : "the planner respects this ceiling"}
            </div>
          </div>
          <div className="card stat">
            <div className="label">This list over 2G</div>
            <div className="value sm">
              {payload ? `${payload.transfer.seconds_on_2g}s` : "—"}
            </div>
            <div className="foot">
              {payload
                ? `${n(payload.transfer.bytes)} bytes · ${payload.transfer.visits} visits · ${payload.transfer.obligations} obligations`
                : ""}
            </div>
          </div>
        </div>
      )}

      {!payload ? (
        <Loading lines={4} />
      ) : (
        <div className="grid cols-2">
          {payload.visits.map((visit) => {
            const allDone = visit.obligations.every((item) =>
              done.has(item.debt_id),
            );
            return (
              <div
                className="card"
                key={visit.ref}
                style={{
                  borderLeft: `3px solid ${
                    allDone
                      ? "var(--good)"
                      : visit.urgent
                        ? "var(--critical)"
                        : "var(--axis)"
                  }`,
                  opacity: allDone ? 0.6 : 1,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 10,
                    alignItems: "flex-start",
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontSize: 18,
                        fontWeight: 640,
                        letterSpacing: "-0.015em",
                      }}
                    >
                      {visit.who}
                    </div>
                    <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                      {visit.age}
                      {visit.sex} · {visit.village} · speaks {visit.language}
                      {visit.phone === "none" ? " · no phone" : ""}
                    </div>
                  </div>
                  {visit.obligations.length > 1 && (
                    <span className="pill warn">
                      {visit.obligations.length} things in one visit
                    </span>
                  )}
                </div>

                {visit.obligations.map((obligation, index) => {
                  const isDone = done.has(obligation.debt_id);
                  return (
                    <div
                      key={obligation.debt_id}
                      style={{
                        marginTop: 12,
                        paddingTop: index === 0 ? 0 : 12,
                        borderTop:
                          index === 0 ? "none" : "1px solid var(--grid)",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: 8,
                          alignItems: "baseline",
                        }}
                      >
                        <span style={{ fontSize: 15, fontWeight: 560 }}>
                          {obligation.why}
                        </span>
                        <span
                          className={`pill ${obligation.days_to_deadline < 0 ? "crit" : ""}`}
                        >
                          {overdueLabel(obligation.days_to_deadline)}
                        </span>
                      </div>

                      {obligation.plan ? (
                        <div style={{ marginTop: 7, fontSize: 13.5 }}>
                          <div>
                            <strong>Plan:</strong> {obligation.plan.what}
                            {obligation.plan.when
                              ? ` — ${obligation.plan.when}`
                              : ""}
                          </div>
                          {obligation.plan.accompany && (
                            <div
                              style={{
                                color: "var(--series-1)",
                                fontWeight: 560,
                              }}
                            >
                              Go with them to this one.
                            </div>
                          )}
                          {obligation.plan.bring.length > 0 && (
                            <div style={{ color: "var(--text-secondary)" }}>
                              Ask them to bring:{" "}
                              {obligation.plan.bring.join(", ")}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div
                          style={{
                            marginTop: 7,
                            fontSize: 13,
                            color: "var(--text-muted)",
                          }}
                        >
                          No plan yet — run the agents on this person from the
                          district view.
                        </div>
                      )}

                      {obligation.plan?.say && (
                        <details style={{ marginTop: 9 }}>
                          <summary
                            style={{
                              fontSize: 12.5,
                              cursor: "pointer",
                              color: "var(--series-1)",
                            }}
                          >
                            What to say at the door
                          </summary>
                          <div
                            className="script"
                            style={{ marginTop: 8, fontSize: 13.5 }}
                          >
                            {obligation.plan.say}
                          </div>
                        </details>
                      )}

                      <div
                        style={{
                          fontSize: 11.5,
                          color: "var(--text-muted)",
                          margin: "9px 0 7px",
                        }}
                      >
                        CLOSES ONLY WITH: {obligation.closes_with_plain}
                      </div>
                      <button
                        className="btn"
                        style={{
                          width: "100%",
                          padding: "11px 14px",
                          fontSize: 14.5,
                        }}
                        disabled={isDone}
                        onClick={() => recordDone(visit, obligation)}
                      >
                        {isDone
                          ? online
                            ? "✓ Recorded"
                            : "✓ Saved on this phone"
                          : "Record it done"}
                      </button>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {payload && (
        <div style={{ marginTop: 16 }}>
          <Card title="Why this screen looks the way it does">
            <p className="note" style={{ marginTop: 0 }}>
              {payload.transfer.note}
            </p>
            <ul style={{ fontSize: 13.3, paddingLeft: 18, margin: "10px 0 0" }}>
              <li style={{ marginBottom: 5 }}>
                <strong>One household is one walk.</strong> Obligations are
                grouped by person, so she is never sent to the same courtyard
                twice in a week because two abnormal results were filed
                separately.
              </li>
              <li style={{ marginBottom: 5 }}>
                <strong>The evidence bar is on the card</strong>, before she
                walks over. She can see that "patient counselled" will not
                close this and a dispensing record will.
              </li>
              <li style={{ marginBottom: 5 }}>
                <strong>Marking a task done works offline.</strong> It is
                queued in local storage and flushed when a connection returns.
                An app that needs a network to record a completed visit does
                not get used.
              </li>
              <li style={{ marginBottom: 5 }}>
                <strong>Her capacity ceiling is real.</strong> The planner
                stops assigning escorts once she hits it, because an ASHA is
                not an infinite resource and pretending otherwise is how
                frontline workers end up unpaid for work the system assumed.
              </li>
              <li>
                <strong>It never shows the diagnosis to a bystander.</strong>{" "}
                The door script says a check-up follow-up is pending, nothing
                more.
              </li>
            </ul>
          </Card>
        </div>
      )}
    </>
  );
}
