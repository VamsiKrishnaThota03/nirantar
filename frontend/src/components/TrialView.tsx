/** The controlled trial.
 *
 * Everything else in this dashboard shows predictions. This runs the block
 * forward ninety days under two arms and counts what happened — with
 * outcomes drawn from a ground-truth model whose coefficients are
 * deliberately *not* the ones the planner optimises against, so the planner
 * is never graded against its own beliefs.
 *
 * The uncomfortable results get the same prominence as the flattering ones.
 * A trial that only reported wins would be marketing.
 */

import { useEffect, useState } from "react";
import { api, type EquityReport, type TrialReport } from "../lib/api";
import { compact, n, n1, pct, rupees } from "../lib/format";
import { LineChart, ReliabilityChart } from "./charts";
import { Card, DataTable, ErrorNote, Legend, Stat } from "./primitives";

const SQ = "var(--series-2)";
const NI = "var(--series-1)";

export function TrialView() {
  const [report, setReport] = useState<TrialReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [days, setDays] = useState(90);
  // One world by default. Locally three trials take about five seconds; on a
  // free container instance with a fraction of a CPU the same work takes two
  // minutes, which looks indistinguishable from a hang. Start fast and let
  // the reader ask for more worlds.
  const [trials, setTrials] = useState(1);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [busy]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.trial({ days, trials }));
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="section-head">
        <h2>A controlled trial, not a claim</h2>
        <p>
          Every other number on this site is a prediction from our own model.
          That is not evidence, so here the block is run forward day by day
          under two arms — the same population, the same daily effort budget,
          the same random luck — and what happens is counted.
        </p>
      </div>

      <div className="banner">
        <span aria-hidden>🔬</span>
        <div>
          <strong>How the circularity is avoided.</strong> The obvious way to
          build this would be to draw each patient's attendance from the
          planner's own predicted no-show. That would be worthless — the
          planner would be graded against its own beliefs and "Nirantar wins"
          would be arithmetic, not a finding. Instead each trial invents a{" "}
          <em>different ground truth</em> by perturbing the published
          coefficients, and the planner never sees it. The question this
          answers is the honest one: <strong>does optimising against an
          imperfect model of human behaviour still help, in a world that
          behaves differently from the model?</strong>
        </div>
      </div>

      <Card
        title="Run it"
        sub="Each trial runs three arms: status quo, Nirantar, and Nirantar with the equity weighting switched off."
      >
        <div className="row">
          <label style={{ fontSize: 13 }}>
            Days{" "}
            <select
              className="icon-btn"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              {[30, 60, 90, 120].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 13 }}>
            Trials{" "}
            <select
              className="icon-btn"
              value={trials}
              onChange={(event) => setTrials(Number(event.target.value))}
            >
              {[1, 3, 5, 8].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <button className="btn" onClick={run} disabled={busy}>
            {busy
              ? `Running… ${elapsed}s`
              : `Run the trial (${trials} ${trials === 1 ? "world" : "worlds"})`}
          </button>
          {report && (
            <span className="pill">
              {report.elapsed_seconds}s for {report.design.trials} trials ×{" "}
              {report.design.days} days × 3 arms
            </span>
          )}
        </div>
        {busy && (
          <p className="note">
            Each world runs three arms over {days} days. About two seconds per
            world on a laptop; roughly forty on a free container instance with
            a fraction of a CPU, so give it a moment — it is working, not
            stuck.
          </p>
        )}
        {!report && !busy && (
          <p className="note">
            A few seconds per world on a laptop, up to a minute on free
            hosting. Nothing is written to the Impact Ledger — simulated
            outcomes must never be mixed into the signed record of real
            closures, which is the only reason that record is worth anything.
          </p>
        )}
      </Card>

      {error && (
        <div style={{ marginTop: 16 }}>
          <ErrorNote error={error} />
        </div>
      )}

      {report && <TrialResults report={report} />}
    </>
  );
}

function TrialResults({ report }: { report: TrialReport }) {
  const { aggregate, burn_down, calibration, equity, design } = report;
  const openSeries = [
    {
      label: "Status quo",
      color: SQ,
      points: burn_down.status_quo.map((row) => ({ x: row.day, y: row.open })),
    },
    {
      label: "Nirantar",
      color: NI,
      points: burn_down.nirantar.map((row) => ({ x: row.day, y: row.open })),
    },
  ];
  const closedSeries = [
    {
      label: "Status quo",
      color: SQ,
      points: burn_down.status_quo.map((row) => ({
        x: row.day,
        y: row.closed_cumulative,
      })),
    },
    {
      label: "Nirantar",
      color: NI,
      points: burn_down.nirantar.map((row) => ({
        x: row.day,
        y: row.closed_cumulative,
      })),
    },
  ];
  const unreachableSeries = [
    {
      label: "Status quo",
      color: SQ,
      points: burn_down.status_quo.map((row) => ({
        x: row.day,
        y: row.unreachable,
      })),
    },
    {
      label: "Nirantar",
      color: NI,
      points: burn_down.nirantar.map((row) => ({
        x: row.day,
        y: row.unreachable,
      })),
    },
  ];

  const legend = [
    { label: "Status quo (due-date queue, conventional referral)", color: SQ },
    { label: "Nirantar", color: NI },
  ];

  return (
    <>
      <div className="grid cols-4" style={{ marginTop: 16 }}>
        <Stat
          label="Obligations closed, Nirantar vs status quo"
          value={`${n1(aggregate.closure_multiple.median)}×`}
          foot={`range ${n1(aggregate.closure_multiple.min)}× – ${n1(aggregate.closure_multiple.max)}× across ${design.trials} worlds`}
          tone="good"
        />
        <Stat
          label="Cost per closure borne by households"
          value={`${n1(aggregate.cost_per_closure_ratio.median * 100)}%`}
          foot="of what the status quo costs per obligation closed"
          tone="good"
        />
        <Stat
          label="Additional healthy life-years discharged"
          value={compact(aggregate.extra_healthy_years.median)}
          foot={`range ${compact(aggregate.extra_healthy_years.min)} – ${compact(aggregate.extra_healthy_years.max)}`}
          tone="good"
        />
        <Stat
          label="Worlds where Nirantar came out ahead"
          value={
            aggregate.nirantar_better_in_all_trials
              ? `${design.trials} of ${design.trials}`
              : "not all"
          }
          foot="each with independently perturbed behaviour"
          tone={aggregate.nirantar_better_in_all_trials ? "good" : "bad"}
        />
      </div>

      <div className="grid split" style={{ marginTop: 16 }}>
        <Card
          title="Backlog burn-down"
          sub="Open obligations remaining, averaged across trials. The status-quo arm barely moves: it works oldest-first and offers journeys people cannot afford."
          table={
            <DataTable
              rows={burn_down.nirantar.filter((_, index) => index % 10 === 0)}
              columns={[
                { head: "Day", cell: (row) => String(row.day) },
                {
                  head: "Status quo open",
                  cell: (row) =>
                    n(
                      burn_down.status_quo.find((item) => item.day === row.day)
                        ?.open ?? 0,
                    ),
                },
                { head: "Nirantar open", cell: (row) => n(row.open) },
              ]}
            />
          }
        >
          <Legend items={legend} />
          <LineChart
            series={openSeries}
            yLabel="Open obligations"
            xLabel="day"
          />
        </Card>

        <Card
          title="Obligations closed, cumulatively"
          sub="Closed means evidence received, not outreach attempted."
          table={
            <DataTable
              rows={burn_down.nirantar.filter((_, index) => index % 10 === 0)}
              columns={[
                { head: "Day", cell: (row) => String(row.day) },
                {
                  head: "Status quo closed",
                  cell: (row) =>
                    n(
                      burn_down.status_quo.find((item) => item.day === row.day)
                        ?.closed_cumulative ?? 0,
                    ),
                },
                { head: "Nirantar closed", cell: (row) => n(row.closed_cumulative) },
              ]}
            />
          }
        >
          <Legend items={legend} />
          <LineChart
            series={closedSeries}
            yLabel="Closed"
            xLabel="day"
          />
        </Card>
      </div>

      <div className="grid split" style={{ marginTop: 16 }}>
        <Card
          title="People the system gave up on"
          sub="After three failed contact attempts an obligation is parked as unreachable. This is the number nobody publishes."
          table={
            <DataTable
              rows={burn_down.nirantar.filter((_, index) => index % 10 === 0)}
              columns={[
                { head: "Day", cell: (row) => String(row.day) },
                {
                  head: "Status quo",
                  cell: (row) =>
                    n(
                      burn_down.status_quo.find((item) => item.day === row.day)
                        ?.unreachable ?? 0,
                    ),
                },
                { head: "Nirantar", cell: (row) => n(row.unreachable) },
              ]}
            />
          }
        >
          <Legend items={legend} />
          <LineChart
            series={unreachableSeries}
            yLabel="Unreachable"
            xLabel="day"
          />
        </Card>

        <Card
          title="Were our predictions any good?"
          sub={calibration.note}
        >
          <ReliabilityChart rows={calibration.nirantar} />
          <div className="row" style={{ marginTop: 10 }}>
            <span className="pill">
              Brier score, Nirantar: {calibration.brier_nirantar}
            </span>
            <span className="pill">
              Status quo: {calibration.brier_status_quo}
            </span>
          </div>
          <p className="note">
            Points <strong>above</strong> the diagonal mean we were optimistic
            — more people stayed away than the model expected. Points{" "}
            <strong>below</strong> it mean we were pessimistic, and more people
            came than we predicted. Either way the distance from the diagonal
            is the error, and it is real: the world's coefficients are not the
            planner's. Bubble size is the number of contacts in that band.
            Lower Brier is better; it is the mean squared error of the no-show
            predictions. This is the figure to discount any single predicted
            attendance number by, and it is published rather than buried.
          </p>
        </Card>
      </div>

      {/* --- equity ----------------------------------------------------- */}
      <div className="section-head">
        <h2>Who got left behind?</h2>
        <p>
          An objective that maximises benefit per unit of effort has a
          standing incentive to work the easy cases: the near, the connected
          and the literate are cheaper to reach and likelier to attend. So a
          system like this has to be audited for exactly that, and the audit
          has to be published whether or not it is flattering.
        </p>
      </div>

      <div className="banner">
        <span aria-hidden>⚖</span>
        <div>
          <strong>What we found.</strong> {equity.what_we_found}
        </div>
      </div>

      <div className="grid split">
        <EquityTable
          title="By distance from the referral hospital"
          sub="Service rate per quintile, nearest first. The status quo favours those living closest; routing care into the village removes the journey, and with it the gradient."
          statusQuo={equity.status_quo}
          nirantar={equity.nirantar}
          strata="by_distance"
          ratioKey="nearest_over_furthest_ratio"
          ratioLabel="nearest ÷ furthest"
          unit="km"
        />
        <EquityTable
          title="By daily wage"
          sub="Poorest quintile first. This is the gap that routing alone does not close — the poorest quintile is largely households with no cash income, and children whose conditions need a specialist."
          statusQuo={equity.status_quo}
          nirantar={equity.nirantar}
          strata="by_wage"
          ratioKey="richest_over_poorest_ratio"
          ratioLabel="richest ÷ poorest"
          unit="₹/day"
        />
      </div>

      <div style={{ marginTop: 16 }}>
        <Card
          title="Does the equity weighting actually do anything?"
          sub="The ranking multiplies expected harm by a vulnerability factor. Here is the same arm with that factor switched off — so the mechanism is measured, not asserted."
        >
          <DataTable
            rows={equity.ablation}
            columns={[
              { head: "Trial", cell: (row) => String(row.trial) },
              {
                head: "Closed, weighted",
                cell: (row) => n(row.with_equity_weighting.closed),
              },
              {
                head: "Closed, unweighted",
                cell: (row) => n(row.without_equity_weighting.closed),
              },
              {
                head: "Wage gap, weighted",
                cell: (row) =>
                  row.with_equity_weighting.richest_over_poorest.toFixed(2),
              },
              {
                head: "Wage gap, unweighted",
                cell: (row) =>
                  row.without_equity_weighting.richest_over_poorest.toFixed(2),
              },
              {
                head: "Distance gap, weighted",
                cell: (row) =>
                  row.with_equity_weighting.nearest_over_furthest.toFixed(2),
              },
              {
                head: "Distance gap, unweighted",
                cell: (row) =>
                  row.without_equity_weighting.nearest_over_furthest.toFixed(2),
              },
            ]}
            caption="Wage gap is the richest quintile's service rate divided by the poorest quintile's; 1.0 would be parity."
          />
          <p className="note">
            The weighting closes <strong>fewer obligations in total</strong> and
            distributes them more evenly. That is a genuine
            efficiency–equity trade-off, and it is presented as one rather than
            as a free win. Which side of it a programme should sit on is a
            decision for the programme, not for this software — so it is a
            single flag, documented, with its cost measured.
          </p>
        </Card>
      </div>

      {/* --- per trial -------------------------------------------------- */}
      <div style={{ marginTop: 16 }}>
        <Card
          title="Every trial, and the world it ran in"
          sub="Each row is an independently perturbed ground truth. The coefficients shown are the world's real behaviour, which the planner never saw."
        >
          <DataTable
            rows={report.trials}
            columns={[
              { head: "Trial", cell: (row) => String(row.trial) },
              {
                head: "SQ closed",
                cell: (row) => n(row.status_quo.obligations_closed),
              },
              {
                head: "NI closed",
                cell: (row) => n(row.nirantar.obligations_closed),
              },
              { head: "×", cell: (row) => n1(row.closure_multiple) },
              {
                head: "SQ attendance",
                cell: (row) => pct(row.status_quo.attendance_rate, 0),
              },
              {
                head: "NI attendance",
                cell: (row) => pct(row.nirantar.attendance_rate, 0),
              },
              {
                head: "SQ ₹/closure",
                cell: (row) => rupees(row.rupees_per_closure_status_quo),
              },
              {
                head: "NI ₹/closure",
                cell: (row) => rupees(row.rupees_per_closure_nirantar),
              },
              {
                head: "Truth: cost weight",
                cell: (row) => n1(row.truth_coefficients.cost),
              },
            ]}
            caption={`The planner believes the cost weight is 1.30. Each trial's world uses a different one, drawn log-normally with a ${pct(design.perturbation_scale, 0)} spread.`}
          />
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card title="Trial design, stated in full">
          <dl className="kv">
            <dt>Days simulated</dt>
            <dd>{design.days}</dd>
            <dt>Independent worlds</dt>
            <dd>{design.trials}</dd>
            <dt>Population</dt>
            <dd>{compact(design.population)}</dd>
            <dt>Daily contact budget</dt>
            <dd>
              {pct(design.daily_contact_share, 1)} of the open backlog, identical
              in both arms
            </dd>
            <dt>Attempts before giving up</dt>
            <dd>{design.max_attempts}</dd>
            <dt>Ground-truth perturbation</dt>
            <dd>{pct(design.perturbation_scale, 0)} log-normal spread</dd>
            <dt>Seed</dt>
            <dd>{design.seed}</dd>
          </dl>
          <p className="note">{design.note}</p>
          <div className="banner" style={{ marginTop: 12, marginBottom: 0 }}>
            <span aria-hidden>⚠</span>
            <div>
              <strong>This is a simulation, not a field trial.</strong>{" "}
              {design.not_a_claim_of_real_impact}
            </div>
          </div>
        </Card>
      </div>
    </>
  );
}

function EquityTable({
  title,
  sub,
  statusQuo,
  nirantar,
  strata,
  ratioKey,
  ratioLabel,
  unit,
}: {
  title: string;
  sub: string;
  statusQuo: EquityReport;
  nirantar: EquityReport;
  strata: "by_distance" | "by_wage";
  ratioKey: "nearest_over_furthest_ratio" | "richest_over_poorest_ratio";
  ratioLabel: string;
  unit: string;
}) {
  const sqRatio = statusQuo[ratioKey];
  const niRatio = nirantar[ratioKey];
  // A 0.02 difference is not a narrowing, and calling it one would be
  // exactly the kind of overclaiming this page exists to avoid. Require a
  // material move before saying anything happened.
  const MATERIAL = 0.05;
  const verdict =
    sqRatio === null || niRatio === null
      ? { text: "", tone: "" }
      : niRatio < sqRatio - MATERIAL
        ? { text: " — narrowed", tone: "good" }
        : niRatio > sqRatio + MATERIAL
          ? { text: " — widened", tone: "crit" }
          : { text: " — essentially unchanged", tone: "warn" };
  const ratio2 = (value: number | null) =>
    value === null ? "—" : value.toFixed(2);

  return (
    <Card title={title} sub={sub}>
      <Legend
        items={[
          { label: "Status quo", color: SQ },
          { label: "Nirantar", color: NI },
        ]}
      />
      <table className="data">
        <thead>
          <tr>
            <th>Quintile</th>
            <th>Mean {unit}</th>
            <th>Status quo</th>
            <th>Nirantar</th>
          </tr>
        </thead>
        <tbody>
          {nirantar[strata].map((row, index) => {
            const sq = statusQuo[strata][index];
            return (
              <tr key={row.stratum}>
                <td>{row.stratum.replace(/^(Distance|Daily wage) /, "")}</td>
                <td>{n1(row.mean_value)}</td>
                <td style={{ color: "var(--text-secondary)" }}>
                  {sq ? pct(sq.served_rate, 1) : "—"}
                </td>
                <td style={{ fontWeight: 600 }}>{pct(row.served_rate, 1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <span className="pill">
          {ratioLabel}, status quo: {ratio2(sqRatio)}
        </span>
        <span className={`pill ${verdict.tone}`}>
          {ratioLabel}, Nirantar: {ratio2(niRatio)}
          {verdict.text}
        </span>
      </div>
      <p className="note">
        Measured over {n(nirantar.people_owed_care)} people{" "}
        {nirantar.denominator}. Only {n(nirantar.people_contacted)} of them
        could be contacted inside the budget, which is why the denominator
        matters: scoring against contacts made would flatter both arms and hide
        the question.
      </p>
    </Card>
  );
}
