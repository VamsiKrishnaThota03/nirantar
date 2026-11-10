/** The district view: the scale of the gap, and where it is worst. */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AgingBucket,
  type BarrierProfile,
  type CascadeStage,
  type Cluster,
  type ConditionRow,
  type EscalationBrief,
  type Overview,
  type PanchayatRow,
  type SupplyGaps,
} from "../lib/api";
import {
  compact,
  dateFull,
  n,
  n1,
  pct,
  rupees,
  rupeesCompact,
} from "../lib/format";
import { BlockSchematic, Funnel, OrdinalBars, RankedBars } from "./charts";
import { Card, DataTable, ErrorNote, Loading, Stat } from "./primitives";

export function DistrictView({ refreshKey }: { refreshKey: number }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [cascade, setCascade] = useState<CascadeStage[]>([]);
  const [aging, setAging] = useState<AgingBucket[]>([]);
  const [conditions, setConditions] = useState<ConditionRow[]>([]);
  const [panchayats, setPanchayats] = useState<PanchayatRow[]>([]);
  const [barriers, setBarriers] = useState<BarrierProfile | null>(null);
  const [gaps, setGaps] = useState<SupplyGaps | null>(null);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [briefs, setBriefs] = useState<EscalationBrief[]>([]);
  const [selectedPanchayat, setSelectedPanchayat] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [writingBriefs, setWritingBriefs] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [
        overviewData,
        cascadeData,
        agingData,
        conditionData,
        panchayatData,
        barrierData,
        gapData,
        clusterData,
        briefData,
      ] = await Promise.all([
        api.overview(),
        api.cascade(),
        api.aging(),
        api.conditions(),
        api.panchayats(),
        api.barriers(),
        api.supplyGaps(),
        api.clusters(),
        api.escalations(),
      ]);
      setOverview(overviewData);
      setCascade(cascadeData);
      setAging(agingData);
      setConditions(conditionData);
      setPanchayats(panchayatData);
      setBarriers(barrierData);
      setGaps(gapData);
      setClusters(clusterData);
      setBriefs(briefData);
    } catch (caught) {
      setError(caught);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function writeBriefs() {
    setWritingBriefs(true);
    try {
      const result = await api.runEscalations(3);
      setBriefs(result.escalations);
    } catch (caught) {
      setError(caught);
    } finally {
      setWritingBriefs(false);
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!overview || !barriers || !gaps) return <Loading lines={8} />;

  const focus = selectedPanchayat
    ? panchayats.find((row) => row.panchayat === selectedPanchayat)
    : null;

  return (
    <>
      {/* --- the headline numbers ------------------------------------------ */}
      <div className="grid cols-4">
        <Stat
          label="People owed care right now"
          value={n(overview.people_with_open_debt)}
          foot={`${pct(overview.share_of_population_owed_care, 1)} of the block's ${compact(overview.population_modelled)} residents`}
          tone="bad"
        />
        <Stat
          label="Obligations past their clinical deadline"
          value={n(overview.care_debts_breached)}
          foot={`of ${n(overview.care_debts_open)} open`}
          tone="bad"
        />
        <Stat
          label="Healthy life-years at stake"
          value={n1(overview.healthy_years_at_stake)}
          foot="if none of these are ever closed"
          tone="bad"
        />
        <Stat
          label="Closed by Nirantar so far"
          value={n(overview.ledger.debts_closed)}
          foot="signed into the Impact Ledger"
          tone="good"
        />
      </div>

      {/* --- the cascade --------------------------------------------------- */}
      <div className="section-head">
        <h2>India finds the problem, then loses the patient</h2>
        <p>
          This is the whole argument. Screening works — it reaches people at
          scale and finds real disease. Then the cascade collapses, not because
          of clinical failure but because nobody owns the step between "we
          found something" and "you were treated".
        </p>
      </div>

      <div className="grid split">
        <Card
          title="Screening cascade"
          sub="Each step down is a real cohort of people who were found and then dropped."
          table={
            <DataTable
              rows={cascade}
              columns={[
                { head: "Stage", cell: (row) => row.stage },
                { head: "People", cell: (row) => n(row.count) },
                {
                  head: "Note",
                  cell: (row) => (
                    <span style={{ whiteSpace: "normal", fontSize: 12 }}>
                      {row.note}
                    </span>
                  ),
                },
              ]}
            />
          }
        >
          <Funnel stages={cascade} />
          <div
            style={{
              marginTop: 14,
              paddingTop: 13,
              borderTop: "1px solid var(--grid)",
              display: "flex",
              gap: 18,
              flexWrap: "wrap",
              alignItems: "baseline",
            }}
          >
            <div>
              <div
                style={{
                  fontSize: 27,
                  fontWeight: 660,
                  letterSpacing: "-0.025em",
                  color: "var(--critical)",
                  lineHeight: 1.1,
                }}
              >
                {n(overview.care_debts_open)}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
                still owed care today, {n(overview.care_debts_breached)} of them
                past their clinical deadline
              </div>
            </div>
            {overview.care_debts_unreachable > 0 && (
              <div>
                <div
                  style={{
                    fontSize: 27,
                    fontWeight: 660,
                    letterSpacing: "-0.025em",
                    lineHeight: 1.1,
                  }}
                >
                  {n(overview.care_debts_unreachable)}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
                  given up on entirely — no working way to reach them
                </div>
              </div>
            )}
          </div>
          <p className="note">
            These three stages describe what the block achieved without
            Nirantar, so they stay a fixed baseline. Anything this system
            closes is counted separately, in the Impact Ledger, where it can be
            audited.
          </p>
        </Card>

        <Card
          title="What a follow-up actually costs, and who therefore does not go"
          sub={`Averaged over a sample of ${n(barriers.sample_size)} open obligations, priced as a conventional referral.`}
        >
          <div className="grid cols-2" style={{ gap: 12 }}>
            <Stat
              label="Average cost to the household"
              value={rupees(barriers.mean_conventional_cost_inr)}
              foot={`${barriers.mean_conventional_travel_km.toFixed(0)} km round trip`}
              small
            />
            <Stat
              label="Predicted not to attend"
              value={pct(barriers.mean_conventional_no_show, 0)}
              foot="under a conventional referral"
              small
            />
          </div>
          <p className="sub" style={{ marginTop: 14, marginBottom: 10 }}>
            Share of these patients facing each barrier:
          </p>
          <RankedBars
            rows={barriers.barriers.slice(0, 7).map((row) => ({
              label: row.barrier,
              value: row.share,
              extra: [{ k: "People in sample", v: n(row.count) }],
            }))}
            valueLabel="Share of patients"
            highlightFirst
            height={230}
            labelWidth={196}
            formatValue={(value) => pct(value, 0)}
          />
          <p className="note">
            Aggregate exposure if every open obligation were pursued
            conventionally:{" "}
            <strong>
              {rupeesCompact(barriers.projected_aggregate_cost_inr)}
            </strong>{" "}
            of out-of-pocket cost loaded onto some of the poorest households in
            the country. Nobody currently measures this, which is why nobody
            optimises it.
          </p>
        </Card>
      </div>

      <div className="grid split" style={{ marginTop: 16 }}>
        <Card
          title="How overdue is the backlog?"
          sub="A breached obligation does not become less important with age — which is precisely the mistake a simple due-date queue makes."
          table={
            <DataTable
              rows={aging}
              columns={[
                { head: "Bucket", cell: (row) => row.bucket },
                { head: "Obligations", cell: (row) => n(row.count) },
                {
                  head: "Healthy years at stake",
                  cell: (row) => n1(row.healthy_years_at_stake),
                },
              ]}
            />
          }
        >
          <OrdinalBars rows={aging} />
        </Card>

        <Card
          title="Where the harm is concentrated"
          sub="Ranked by healthy life-years at stake, so that severity rather than volume sets the order."
          table={
            <DataTable
              rows={conditions}
              columns={[
                { head: "Condition", cell: (row) => row.label },
                { head: "Open", cell: (row) => n(row.open) },
                { head: "Overdue", cell: (row) => n(row.breached) },
                {
                  head: "Closure rate today",
                  cell: (row) => pct(row.closure_rate, 0),
                },
                {
                  head: "Healthy yrs",
                  cell: (row) => n1(row.healthy_years_at_stake),
                },
              ]}
            />
          }
        >
          <RankedBars
            rows={conditions.slice(0, 8).map((row) => ({
              label: row.label,
              value: row.healthy_years_at_stake,
              extra: [
                { k: "Open obligations", v: n(row.open) },
                { k: "Past deadline", v: n(row.breached) },
                { k: "Closure rate today", v: pct(row.closure_rate, 0) },
                { k: "Clinical deadline", v: `${row.deadline_days} days` },
              ],
            }))}
            valueLabel="Healthy life-years at stake"
            sequential
            height={260}
            labelWidth={226}
            formatValue={(value) => n1(value)}
          />
        </Card>
      </div>

      {/* --- geography ----------------------------------------------------- */}
      <div className="section-head">
        <h2>The places that need outreach most get it least</h2>
        <p>
          A schematic of {BLOCK_LABEL(overview)} — twelve panchayats, shaded by
          the healthy life-years currently at stake in each. This is a
          schematic, not a geographic map; no real coordinates are claimed. Note
          which tiles carry a warning flag: the two panchayats furthest from the
          district hospital are the two the mobile medical units do not reach.
        </p>
      </div>

      <Card
        title="Block schematic"
        sub="Click a panchayat for its detail."
        table={
          <DataTable
            rows={panchayats}
            columns={[
              { head: "Panchayat", cell: (row) => row.panchayat },
              { head: "Population", cell: (row) => n(row.population) },
              { head: "Open", cell: (row) => n(row.open) },
              { head: "Overdue", cell: (row) => n(row.breached) },
              { head: "Per 1,000", cell: (row) => n1(row.open_per_1000) },
              {
                head: "Healthy yrs",
                cell: (row) => n1(row.healthy_years_at_stake),
              },
              { head: "km to DH", cell: (row) => n1(row.km_to_district_hospital) },
              {
                head: "Next outreach",
                cell: (row) =>
                  row.next_outreach_visit
                    ? dateFull(row.next_outreach_visit)
                    : "none scheduled",
              },
            ]}
          />
        }
      >
        <BlockSchematic
          rows={panchayats}
          onSelect={setSelectedPanchayat}
          selected={selectedPanchayat}
        />
        {focus && (
          <div
            style={{
              marginTop: 16,
              paddingTop: 14,
              borderTop: "1px solid var(--grid)",
            }}
          >
            <h3 style={{ margin: "0 0 8px" }}>{focus.panchayat}</h3>
            <dl className="kv">
              <dt>Population</dt>
              <dd>{n(focus.population)}</dd>
              <dt>People owed care</dt>
              <dd>
                {n(focus.people_owed_care)} ({n1(focus.open_per_1000)} per
                1,000)
              </dd>
              <dt>Past clinical deadline</dt>
              <dd>{n(focus.breached)}</dd>
              <dt>Healthy years at stake</dt>
              <dd>{n1(focus.healthy_years_at_stake)}</dd>
              <dt>Distance to district hospital</dt>
              <dd>{n1(focus.km_to_district_hospital)} km</dd>
              <dt>Next outreach visit</dt>
              <dd>
                {focus.next_outreach_visit ? (
                  `${dateFull(focus.next_outreach_visit)} (in ${focus.days_until_outreach} days)`
                ) : (
                  <span className="pill crit">none scheduled in 28 days</span>
                )}
              </dd>
              {focus.unstaffed_facilities.length > 0 && (
                <>
                  <dt>Unstaffed facilities</dt>
                  <dd>{focus.unstaffed_facilities.join(", ")}</dd>
                </>
              )}
            </dl>
          </div>
        )}
      </Card>

      {/* --- supply side --------------------------------------------------- */}
      <div className="section-head">
        <h2>Why obligations cannot be closed</h2>
        <p>
          Almost none of these failures are clinical and none are the patient's
          fault. They are a van that does not come, a shelf that is empty, a
          post that is vacant, and a specialist diary with no room in it.
          Grouping failures by shared cause turns eight thousand individual
          problems into a handful of decisions a block medical officer can
          actually make.
        </p>
      </div>

      <div className="grid cols-4">
        <Stat
          label="Facility stock-outs"
          value={n(gaps.stockout_count)}
          foot="drug-facility pairs below ten units"
          tone="bad"
        />
        <Stat
          label="Specialist capacity"
          value={pct(gaps.specialist_capacity_ratio, 0)}
          foot={`${n(gaps.specialist_slots_next_14d)} slots for ${n(gaps.specialist_reviews_owed)} reviews owed`}
          tone="bad"
        />
        <Stat
          label="Panchayats with no outreach in 14 days"
          value={n(gaps.panchayats_without_outreach_14d.length)}
          foot={gaps.panchayats_without_outreach_14d.join(", ") || "none"}
          tone="bad"
        />
        <Stat
          label="Unstaffed facilities"
          value={n(gaps.unstaffed_facilities.length)}
          foot={
            gaps.unstaffed_facilities.map((item) => item.panchayat).join(", ") ||
            "none"
          }
          tone="bad"
        />
      </div>

      <div className="grid split" style={{ marginTop: 16 }}>
        <Card
          title="Blocked clusters, ranked by harm accumulating"
          sub="Forty untreated TB cases outrank four hundred overdue BP rechecks. A count-ordered list gets that exactly backwards."
          table={
            <DataTable
              rows={clusters}
              columns={[
                { head: "Cause", cell: (row) => row.cause_label },
                { head: "Where", cell: (row) => row.panchayat },
                { head: "Obligations", cell: (row) => n(row.count) },
                { head: "People", cell: (row) => n(row.people_affected) },
                {
                  head: "Healthy yrs",
                  cell: (row) => n1(row.healthy_years_at_stake),
                },
              ]}
            />
          }
        >
          <div style={{ display: "grid", gap: 11 }}>
            {clusters.slice(0, 5).map((cluster) => (
              <div
                key={`${cluster.cause}-${cluster.panchayat}`}
                style={{
                  borderLeft: "3px solid var(--critical)",
                  paddingLeft: 11,
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                  {cluster.cause_label} — {cluster.panchayat}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
                  {n(cluster.count)} obligations · {n(cluster.people_affected)}{" "}
                  people · {n(cluster.breached_count)} past deadline, oldest by{" "}
                  {cluster.oldest_days_overdue} days ·{" "}
                  <strong>{n1(cluster.healthy_years_at_stake)}</strong> healthy
                  years at stake
                </div>
                <div
                  style={{
                    fontSize: 12.5,
                    marginTop: 3,
                    color: "var(--text-primary)",
                  }}
                >
                  <strong>Fix:</strong> {cluster.remedy}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Briefs for the Block Medical Officer"
          sub="One page per cluster, opening with the decision requested rather than with background."
          aside={
            <button
              className="btn secondary"
              style={{ marginLeft: "auto" }}
              onClick={writeBriefs}
              disabled={writingBriefs}
            >
              {writingBriefs ? "Writing…" : "Write briefs"}
            </button>
          }
        >
          {briefs.length === 0 ? (
            <p className="sub">
              No briefs yet. Generate them from the top blocked clusters.
            </p>
          ) : (
            <div style={{ display: "grid", gap: 14, maxHeight: 460, overflowY: "auto" }}>
              {briefs.map((brief) => (
                <article key={brief.id} className="md">
                  <div className="row" style={{ marginBottom: 6 }}>
                    <span className="pill crit">{brief.panchayat}</span>
                    <span className="pill">
                      {brief.generated_by === "llm" ? "Claude" : "template"}
                    </span>
                    <span className="pill">{dateFull(brief.raised_on)}</span>
                  </div>
                  <div style={{ fontWeight: 620, fontSize: 14 }}>
                    {brief.headline}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      whiteSpace: "pre-wrap",
                      color: "var(--text-secondary)",
                      marginTop: 6,
                    }}
                  >
                    {brief.brief_markdown.replace(/\*\*/g, "")}
                  </div>
                </article>
              ))}
            </div>
          )}
          <p className="note">
            Escalations are raised against system failures, never against
            patients. "Non-compliant patient" is not a category anywhere in
            this codebase — if someone cannot attend, the plan was wrong.
          </p>
        </Card>
      </div>

      {gaps.stockouts.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card
            title="Stock-outs, worst first"
            sub="Checked before anyone is asked to travel. Routing a patient to an empty shelf is the most expensive kind of nothing."
          >
            <DataTable
              rows={gaps.stockouts.slice(0, 14)}
              columns={[
                { head: "Facility", cell: (row) => row.facility },
                { head: "Panchayat", cell: (row) => row.panchayat },
                { head: "Drug", cell: (row) => row.drug },
                { head: "Units on hand", cell: (row) => n(row.units) },
              ]}
            />
          </Card>
        </div>
      )}
    </>
  );
}

const BLOCK_LABEL = (overview: Overview) =>
  `${overview.block} block, ${overview.district} district`;
