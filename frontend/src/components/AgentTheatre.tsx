/** The agent theatre: watch five agents plan one person's care, live.
 *
 * This view exists because the interesting claim is not "we built a
 * dashboard", it is "here is the reasoning, step by step, with the
 * alternatives it rejected and why". So the pipeline streams, each stage
 * reports its own measured duration, and the plan is shown next to the
 * referral a conventional system would have issued instead.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  streamPlan,
  type AgentStep,
  type CarePlan,
  type StreamFrame,
  type WorklistRow,
} from "../lib/api";
import {
  dateFull,
  n1,
  overdueLabel,
  pct,
  rupees,
  titleCase,
} from "../lib/format";
import { CompareBars, DivergingBars } from "./charts";
import { Card, DataTable, ErrorNote, Legend, Loading } from "./primitives";

const AGENTS = ["Triage", "Reality", "Supply", "Planner", "Verifier"] as const;

/** Speaks a script with the browser's own speech synthesis.
 *
 * Not the production voice path — a real deployment hands the script to a
 * telephony provider with a trained Indic voice. This exists so the script
 * can be *heard* rather than only read, because "voice-first for people who
 * cannot read an SMS" is the central design claim and a wall of Devanagari
 * on a dashboard does not demonstrate it.
 */
function useSpeech() {
  const [speaking, setSpeaking] = useState(false);
  const supported =
    typeof window !== "undefined" && "speechSynthesis" in window;

  const stop = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback(
    (text: string, langCode: string) => {
      if (!supported) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      // Indic voices are usually registered under hi-IN; Bhojpuri, Awadhi
      // and Maithili have no system voice, so Hindi is the closest available
      // rendering and we say so in the interface rather than implying the
      // dialect is supported.
      utterance.lang = langCode === "bho" ? "hi-IN" : "hi-IN";
      // Slower than default: this is health information for someone who may
      // be hearing it over a poor line.
      utterance.rate = 0.85;
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      setSpeaking(true);
      window.speechSynthesis.speak(utterance);
    },
    [supported],
  );

  useEffect(() => stop, [stop]);
  return { speak, stop, speaking, supported };
}

const AGENT_BLURB: Record<string, string> = {
  Triage: "ranks by expected harm",
  Reality: "prices the barriers",
  Supply: "finds real capacity",
  Planner: "optimises the path",
  Verifier: "sets the evidence bar",
};

export function AgentTheatre({ onLedgerChange }: { onLedgerChange: () => void }) {
  const [rows, setRows] = useState<WorklistRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<WorklistRow | null>(null);
  const [conditionFilter, setConditionFilter] = useState<string>("");

  const [running, setRunning] = useState(false);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [plan, setPlan] = useState<CarePlan | null>(null);
  const [overrides, setOverrides] = useState<string[]>([]);
  const [noPlan, setNoPlan] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [closed, setClosed] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const speech = useSpeech();

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.worklist({
        limit: 24,
        condition: conditionFilter || undefined,
      });
      setRows(data);
      setSelected((current) => current ?? data[0] ?? null);
    } catch (caught) {
      setError(caught);
    }
  }, [conditionFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => abort.current?.abort(), []);

  const reset = () => {
    setSteps([]);
    setPlan(null);
    setOverrides([]);
    setNoPlan(false);
    setRunError(null);
    setClosed(null);
    setActiveAgent(null);
  };

  async function run() {
    if (!selected) return;
    reset();
    setRunning(true);
    abort.current?.abort();
    abort.current = new AbortController();
    try {
      await streamPlan(
        selected.debt_id,
        (frame: StreamFrame) => {
          if (frame.type === "agent_started") setActiveAgent(frame.agent);
          else if (frame.type === "agent_step")
            setSteps((current) => [...current, frame.step]);
          else if (frame.type === "run_finished") {
            setPlan(frame.plan);
            setNoPlan(frame.no_viable_plan);
            setOverrides(frame.safety_overrides ?? []);
            setActiveAgent(null);
          } else if (frame.type === "error") setRunError(frame.error);
        },
        abort.current.signal,
      );
      onLedgerChange();
    } catch (caught) {
      if ((caught as Error).name !== "AbortError")
        setRunError(
          caught instanceof Error ? caught.message : "The agent run failed.",
        );
    } finally {
      setRunning(false);
      setActiveAgent(null);
    }
  }

  async function closeWithEvidence() {
    if (!selected || !plan) return;
    const kinds: Record<string, string> = {
      refill_medication: "drug_dispensed",
      confirm_diagnosis: "bp_recorded",
      followup_test: "test_result_received",
      initiate_treatment: "treatment_initiated",
      specialist_review: "specialist_note",
      routine_visit: "visit_logged",
    };
    try {
      const result = await api.closeDebt(selected.debt_id, {
        kind: kinds[selected.required_action] ?? "visit_logged",
        detail: `Recorded at ${plan.strategy}.`,
        recorded_by: plan.asha_id ?? "facility-staff",
      });
      setClosed(
        `Closed and written to the signed ledger as entry #${result.decision.ledger_entry.seq}.`,
      );
      onLedgerChange();
      void load();
    } catch (caught) {
      setRunError(
        caught instanceof Error ? caught.message : "Could not close this.",
      );
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!rows) return <Loading lines={6} />;

  const barriers =
    steps.find((step) => step.agent === "Reality")?.detail?.barriers ?? [];
  const shortlist =
    steps.find((step) => step.agent === "Planner")?.detail?.shortlist ?? [];
  const narrative = steps.find((step) => step.agent === "Reality")?.detail
    ?.narrative as string | undefined;
  const triage = steps.find((step) => step.agent === "Triage")?.detail;
  const rejected =
    steps.find((step) => step.agent === "Supply")?.detail?.rejected ?? [];

  return (
    <>
      <div className="section-head">
        <h2>Watch the agents work</h2>
        <p>
          Pick anyone from the block's worklist. The five agents run in sequence
          and report as they go — the durations below are measured, not
          animated. Everything the planner rejected is shown too, because the
          rejections are where the clinical judgement lives.
        </p>
      </div>

      <div className="grid split">
        <Card
          title="Block worklist"
          sub="Ordered by expected harm if never closed, not by date received. The person at the top is the person the block should chase first."
          aside={
            <select
              className="icon-btn"
              value={conditionFilter}
              onChange={(event) => {
                setConditionFilter(event.target.value);
                setSelected(null);
                reset();
              }}
              aria-label="Filter by condition"
              style={{ marginLeft: "auto" }}
            >
              <option value="">All conditions</option>
              <option value="tb_confirmed_not_initiated">TB, not started</option>
              <option value="hypertension_refill_due">BP refill overdue</option>
              <option value="hypertension_suspect">Raised BP, unconfirmed</option>
              <option value="diabetes_suspect">Raised sugar, unconfirmed</option>
              <option value="anaemia_pregnancy_severe">Severe anaemia in pregnancy</option>
              <option value="child_sam_suspect">Child malnutrition</option>
              <option value="oral_cancer_suspect">Suspicious oral lesion</option>
            </select>
          }
        >
          <div style={{ maxHeight: 430, overflowY: "auto", margin: "0 -6px" }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Obligation</th>
                  <th>Deadline</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.debt_id}
                    onClick={() => {
                      setSelected(row);
                      reset();
                    }}
                    style={{
                      cursor: "pointer",
                      background:
                        selected?.debt_id === row.debt_id
                          ? "color-mix(in srgb, var(--series-1) 11%, transparent)"
                          : undefined,
                    }}
                  >
                    <td>
                      <div style={{ fontWeight: 560 }}>
                        {row.person.display_name}
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                        {row.person.age}
                        {row.person.sex === "female" ? "F" : "M"} ·{" "}
                        {row.person.village} · {row.person.language}
                      </div>
                    </td>
                    <td style={{ textAlign: "left", fontSize: 12.5 }}>
                      {row.label}
                    </td>
                    <td>
                      <span
                        className={`pill ${row.breached ? "crit" : "good"}`}
                      >
                        {overdueLabel(row.days_to_deadline)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="The case">
          {!selected ? (
            <p className="sub">Select someone from the worklist.</p>
          ) : (
            <>
              <div
                style={{
                  fontSize: 19,
                  fontWeight: 640,
                  letterSpacing: "-0.02em",
                }}
              >
                {selected.person.display_name}
              </div>
              <div
                style={{
                  color: "var(--text-secondary)",
                  fontSize: 13,
                  marginBottom: 12,
                }}
              >
                {selected.person.age}-year-old{" "}
                {selected.person.sex === "female" ? "woman" : "man"}
                {selected.person.is_pregnant ? ", pregnant" : ""} ·{" "}
                {selected.person.village}, {selected.person.panchayat}
              </div>
              <dl className="kv">
                <dt>Obligation</dt>
                <dd>{selected.label}</dd>
                <dt>Action needed</dt>
                <dd>{titleCase(selected.required_action)}</dd>
                <dt>Open since</dt>
                <dd>{dateFull(selected.opened_on)}</dd>
                <dt>Clinical deadline</dt>
                <dd>
                  {dateFull(selected.deadline_on)}{" "}
                  <span className={selected.breached ? "pill crit" : "pill good"}>
                    {overdueLabel(selected.days_to_deadline)}
                  </span>
                </dd>
                <dt>Daily wage</dt>
                <dd>
                  {selected.person.daily_wage_inr > 0
                    ? rupees(selected.person.daily_wage_inr)
                    : "no cash wage"}
                </dd>
                <dt>To district hospital</dt>
                <dd>{selected.person.km_to_district.toFixed(0)} km</dd>
                <dt>Reading</dt>
                <dd>{titleCase(selected.person.literacy)}</dd>
                <dt>Phone</dt>
                <dd>{titleCase(selected.person.phone_type)}</dd>
                <dt>Speaks</dt>
                <dd>{selected.person.language}</dd>
              </dl>
              <div className="row" style={{ marginTop: 16 }}>
                <button className="btn" onClick={run} disabled={running}>
                  {running ? "Agents working…" : "Run the agents"}
                </button>
                {plan && !closed && (
                  <button className="btn secondary" onClick={closeWithEvidence}>
                    Record evidence &amp; close
                  </button>
                )}
              </div>
              {closed && (
                <p
                  style={{
                    color: "var(--success-text)",
                    fontSize: 13,
                    marginTop: 10,
                  }}
                >
                  ✓ {closed}
                </p>
              )}
              <p className="note">
                All records here are generated and fictional. No real person's
                health data is present in this demo.
              </p>
            </>
          )}
        </Card>
      </div>

      {(running || steps.length > 0) && (
        <div style={{ marginTop: 16 }}>
          <Card
            title="Agent trace"
            sub="Each row appears when that agent finishes. Durations are wall-clock."
          >
            {AGENTS.map((agent) => {
              const step = steps.find((item) => item.agent === agent);
              const isActive = activeAgent === agent;
              return (
                <div className="agent-row" key={agent}>
                  <div>
                    <div className="agent-name">
                      <span
                        className={`dot${step ? " done" : isActive ? " active" : ""}`}
                      />
                      {agent}
                    </div>
                    <div className="agent-phase">{AGENT_BLURB[agent]}</div>
                  </div>
                  <div className="agent-summary">
                    {step ? (
                      <>
                        {step.summary}
                        {step.used_llm && (
                          <span className="pill" style={{ marginLeft: 8 }}>
                            Claude
                          </span>
                        )}
                      </>
                    ) : isActive ? (
                      <span style={{ color: "var(--text-muted)" }}>
                        <span className="spin" /> working…
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)" }}>queued</span>
                    )}
                  </div>
                  <div className="agent-ms">
                    {step
                      ? step.duration_ms < 1
                        ? "<1 ms"
                        : `${step.duration_ms} ms`
                      : ""}
                  </div>
                </div>
              );
            })}
            {runError && (
              <div className="banner" style={{ marginTop: 14 }}>
                <span aria-hidden>⚠</span>
                <div>{runError}</div>
              </div>
            )}
          </Card>
        </div>
      )}

      {noPlan && (
        <div className="banner" style={{ marginTop: 16 }}>
          <span aria-hidden>⚠</span>
          <div>
            <strong>No viable plan exists for this person.</strong> Nothing in
            the block can discharge this obligation inside its clinical deadline
            with the medicine in stock. Rather than issue a referral that would
            waste a day's wages, the system escalates this as a supply failure —
            see the Escalations section.
          </div>
        </div>
      )}

      {plan && (
        <>
          <div className="grid split" style={{ marginTop: 16 }}>
            <Card
              title="The plan"
              sub={plan.rationale}
              aside={
                <span className="pill good" style={{ marginLeft: "auto" }}>
                  {plan.generated_by === "llm"
                    ? "Claude-selected"
                    : "deterministic"}
                </span>
              }
            >
              <div
                style={{
                  fontSize: 17,
                  fontWeight: 620,
                  letterSpacing: "-0.015em",
                  marginBottom: 10,
                }}
              >
                {plan.strategy}
              </div>
              <ol style={{ margin: "0 0 14px", paddingLeft: 20, fontSize: 13.3 }}>
                {plan.steps.map((step) => (
                  <li key={step.order} style={{ marginBottom: 5 }}>
                    <b style={{ fontWeight: 600 }}>{titleCase(step.actor)}:</b>{" "}
                    {step.action}
                    {step.on_date && (
                      <span style={{ color: "var(--text-muted)" }}>
                        {" "}
                        — {dateFull(step.on_date)}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
              {plan.artifacts.stock_reservation && (
                <p className="note" style={{ marginTop: 0 }}>
                  <strong>Stock reserved:</strong>{" "}
                  {plan.artifacts.stock_reservation.units} units of{" "}
                  {plan.artifacts.stock_reservation.drug} held before the patient
                  is asked to travel.
                </p>
              )}
              {overrides.length > 0 && (
                <div className="banner" style={{ marginTop: 12 }}>
                  <span aria-hidden>🛡</span>
                  <div>
                    <strong>Safety guardrail fired.</strong>
                    <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                      {overrides.map((item) => (
                        <li key={item} style={{ fontSize: 12.5 }}>
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </Card>

            <Card
              title="Against a conventional referral"
              sub={plan.counterfactual.description}
              table={
                <DataTable
                  rows={[
                    {
                      measure: "Cost to the household",
                      conventional: rupees(plan.counterfactual.cost_inr),
                      nirantar: rupees(plan.cost.total_inr),
                    },
                    {
                      measure: "Round-trip travel",
                      conventional: `${plan.counterfactual.travel_km.toFixed(0)} km`,
                      nirantar: `${plan.cost.travel_km.toFixed(0)} km`,
                    },
                    {
                      measure: "Working days lost",
                      conventional: n1(plan.counterfactual.wage_loss_days),
                      nirantar: n1(plan.cost.wage_loss_days),
                    },
                    {
                      measure: "Predicted no-show",
                      conventional: pct(plan.counterfactual.no_show, 0),
                      nirantar: pct(plan.predicted_no_show, 0),
                    },
                  ]}
                  columns={[
                    { head: "Measure", cell: (row) => row.measure },
                    { head: "Conventional", cell: (row) => row.conventional },
                    { head: "Nirantar", cell: (row) => row.nirantar },
                  ]}
                />
              }
            >
              <Legend
                items={[
                  { label: "Conventional referral", color: "var(--series-2)" },
                  { label: "Nirantar plan", color: "var(--series-1)" },
                ]}
              />
              <CompareBars
                metrics={[
                  {
                    label: "Cost to the household",
                    conventional: plan.counterfactual.cost_inr,
                    nirantar: plan.cost.total_inr,
                    format: (value) => rupees(value),
                  },
                  {
                    label: "Round-trip travel",
                    conventional: plan.counterfactual.travel_km,
                    nirantar: plan.cost.travel_km,
                    format: (value) => `${value.toFixed(0)} km`,
                  },
                  {
                    label: "Working days lost",
                    conventional: plan.counterfactual.wage_loss_days,
                    nirantar: plan.cost.wage_loss_days,
                    format: (value) => n1(value),
                  },
                  {
                    label: "Predicted chance of not attending",
                    conventional: plan.counterfactual.no_show,
                    nirantar: plan.predicted_no_show,
                    format: (value) => pct(value, 0),
                  },
                ]}
              />
              <p className="note">
                The conventional comparison is not a straw man: it is a referral
                to the highest-capability facility for the condition, on that
                facility's next free slot, notified by SMS — which is what a
                correctly operating referral system does today.
              </p>
            </Card>
          </div>

          <div className="grid split" style={{ marginTop: 16 }}>
            <Card
              title={`Outreach — ${plan.artifacts.channel_label}`}
              sub={
                plan.artifacts.channel === "asha_visit"
                  ? "There is no phone in this household, so the only channel is a health worker at the door. This is what she will say."
                  : "Voice first, because a quarter of adults here cannot read an SMS. The message never names the diagnosis: handsets are frequently shared."
              }
            >
              {plan.artifacts.outreach_blocked && (
                <div className="banner" style={{ marginTop: 0 }}>
                  <span aria-hidden>⚠</span>
                  <div>
                    <strong>This patient cannot currently be told.</strong> No
                    phone in the household and no ASHA with capacity this week.
                    The plan is clinically sound but undeliverable, so it is
                    escalated as a contact-channel failure rather than recorded
                    as outreach.
                  </div>
                </div>
              )}
              <div className="script" lang="hi">
                {plan.artifacts.voice_script.script}
              </div>
              <div className="gloss">
                <strong style={{ fontSize: 11.5, letterSpacing: "0.04em" }}>
                  ENGLISH GLOSS FOR SUPERVISORS
                </strong>
                {"\n"}
                {plan.artifacts.voice_script.english_gloss}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                {speech.supported && (
                  <button
                    className="btn secondary"
                    onClick={() =>
                      speech.speaking
                        ? speech.stop()
                        : speech.speak(
                            plan.artifacts.voice_script.script,
                            plan.artifacts.voice_script.language_code,
                          )
                    }
                  >
                    {speech.speaking ? "■ Stop" : "▶ Hear it"}
                  </button>
                )}
                {plan.artifacts.channel !== "asha_visit" && (
                  <>
                    <span className="pill">
                      ~{plan.artifacts.voice_script.estimated_duration_seconds}s
                      message
                    </span>
                    <span className="pill">
                      {plan.artifacts.voice_script.retry_policy.attempts}{" "}
                      attempts, then a home visit
                    </span>
                  </>
                )}
                {plan.artifacts.voice_script.requires_native_review && (
                  <span className="pill warn">
                    awaiting native-speaker review
                  </span>
                )}
                {plan.artifacts.voice_script.fell_back_to_hindi && (
                  <span className="pill warn">
                    no copy yet in {plan.outreach_language} — delivered in
                    Hindi, and the model counts that as a barrier still standing
                  </span>
                )}
              </div>
              <p className="note">
                {plan.artifacts.voice_script.privacy_note}
              </p>
              {speech.supported && (
                <p className="note">
                  "Hear it" uses your browser's own speech synthesis, so the
                  pronunciation is whatever Hindi voice your device ships. A
                  real deployment hands this script to a telephony provider
                  with a trained Indic voice; this is here so the script can be
                  heard rather than only read.
                </p>
              )}
            </Card>

            <Card
              title="What the planner considered"
              sub="Every option the arithmetic priced, including the ones it threw away. A recommendation you cannot interrogate is not a recommendation."
              table={
                <DataTable
                  rows={shortlist as any[]}
                  columns={[
                    { head: "Option", cell: (row) => row.label },
                    { head: "Cost", cell: (row) => rupees(row.cost_inr) },
                    { head: "km", cell: (row) => row.travel_km.toFixed(0) },
                    { head: "No-show", cell: (row) => pct(row.no_show, 0) },
                    { head: "Score", cell: (row) => row.score.toFixed(2) },
                  ]}
                  caption="Lower score is better. Score = expected harm + patient burden + system cost + any deadline penalty."
                />
              }
            >
              <table className="data">
                <thead>
                  <tr>
                    <th>Option</th>
                    <th>Cost</th>
                    <th>No-show</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {(shortlist as any[]).map((row) => (
                    <tr key={row.label}>
                      <td>
                        {row.chosen && (
                          <span
                            style={{
                              color: "var(--success-text)",
                              fontWeight: 700,
                            }}
                          >
                            ✓{" "}
                          </span>
                        )}
                        {row.label}
                        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                          {row.on_date ? dateFull(row.on_date) : "unscheduled"}
                          {row.within_deadline
                            ? ""
                            : " · misses clinical deadline"}
                        </div>
                      </td>
                      <td>{rupees(row.cost_inr)}</td>
                      <td>{pct(row.no_show, 0)}</td>
                      <td>{row.score.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(rejected as any[]).length > 0 && (
                <>
                  <p
                    className="note"
                    style={{ marginBottom: 4, marginTop: 14 }}
                  >
                    <strong>Ruled out before costing:</strong>
                  </p>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
                    {(rejected as any[]).map((row, index) => (
                      <li key={index} style={{ color: "var(--text-secondary)" }}>
                        {row.label} — {row.why}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>
          </div>
        </>
      )}

      {barriers.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card
            title="Why this person would not have attended"
            sub={
              narrative ??
              "Each bar is a named, actionable obstacle, measured in log-odds of not attending."
            }
            table={
              <DataTable
                rows={barriers as any[]}
                columns={[
                  { head: "Barrier", cell: (row) => row.barrier },
                  { head: "Log-odds", cell: (row) => row.log_odds.toFixed(3) },
                  { head: "Effect", cell: (row) => row.direction },
                  { head: "Detail", cell: (row) => row.detail },
                ]}
              />
            }
          >
            <Legend
              items={[
                { label: "Raises no-show risk", color: "var(--critical)" },
                { label: "Lowers no-show risk", color: "var(--series-1)" },
              ]}
            />
            <DivergingBars rows={barriers as any[]} />
            {triage && (
              <p className="note">
                <strong>Triage:</strong> risk {n1(triage.final_score)}/100 —
                severity weight {triage.severity_daly_weight} healthy years ×
                urgency {n1(triage.urgency_multiplier)} × vulnerability{" "}
                {n1(triage.vulnerability_multiplier)}
                {Array.isArray(triage.vulnerability_reasons) &&
                triage.vulnerability_reasons.length > 0
                  ? ` (${triage.vulnerability_reasons.join(", ")})`
                  : ""}
                .
              </p>
            )}
          </Card>
        </div>
      )}

      {plan && (
        <div style={{ marginTop: 16 }}>
          <Card
            title="What it will take to close this"
            sub="Declared before the outreach goes out, so it cannot be renegotiated afterwards."
          >
            <div className="row">
              {(
                steps.find((step) => step.agent === "Verifier")?.detail
                  ?.in_plain_words ?? []
              ).map((item: string) => (
                <span className="pill good" key={item}>
                  ✓ {item}
                </span>
              ))}
            </div>
            <p className="note">
              <strong>Will not be accepted:</strong>{" "}
              {(
                steps.find((step) => step.agent === "Verifier")?.detail
                  ?.will_not_accept ?? []
              ).join(" · ")}
              . Outreach is an input, not an outcome: there is no code path
              through which a care obligation can be marked closed without an
              evidence payload.
            </p>
          </Card>
        </div>
      )}
    </>
  );
}
