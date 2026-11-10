/** Method and provenance.
 *
 * Here because a model whose assumptions you cannot inspect is not evidence
 * of anything. Every calibrated constant is listed with its source, and the
 * ones we had to assume are labelled as assumptions rather than buried.
 */

import { useEffect, useState } from "react";
import { api, type CalibrationPayload } from "../lib/api";
import { titleCase } from "../lib/format";
import { Card, DataTable, ErrorNote, Loading } from "./primitives";

export function MethodView() {
  const [data, setData] = useState<CalibrationPayload | null>(null);
  const [usage, setUsage] = useState<Awaited<
    ReturnType<typeof api.llmUsage>
  > | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [calibration, llm] = await Promise.all([
          api.calibration(),
          api.llmUsage(),
        ]);
        setData(calibration);
        setUsage(llm);
      } catch (caught) {
        setError(caught);
      }
    })();
  }, []);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading lines={6} />;

  const published = data.constants.filter((item) => item.assumed === "no");
  const assumed = data.constants.filter((item) => item.assumed === "yes");

  return (
    <>
      <div className="section-head">
        <h2>Method, sources, and what we assumed</h2>
        <p>{data.note}</p>
      </div>

      <div className="grid split">
        <Card
          title="How the agents divide the work"
          sub="A fixed pipeline rather than a free-form agent loop, because each stage has a different correctness requirement."
        >
          <dl className="kv" style={{ gap: "9px 14px" }}>
            <dt>
              <strong>Triage</strong>
            </dt>
            <dd>
              Deterministic risk formula; the model may adjust the score by at
              most ±12 and can never de-prioritise a critical condition.
            </dd>
            <dt>
              <strong>Reality</strong>
            </dt>
            <dd>
              Prices the conventional referral and decomposes the no-show
              prediction into named barriers. The model writes the narrative.
            </dd>
            <dt>
              <strong>Supply</strong>
            </dt>
            <dd>
              Pure inventory and capacity lookup. No model involvement at all —
              a hallucinated appointment slot would put a sick person on a bus
              for nothing.
            </dd>
            <dt>
              <strong>Planner</strong>
            </dt>
            <dd>
              Constrained optimisation, then the model chooses among the top
              three and writes the outreach. It cannot invent an option, change
              a date, override stock, or trade away a clinical deadline.
            </dd>
            <dt>
              <strong>Verifier</strong>
            </dt>
            <dd>
              Entirely deterministic. The model may flag an entry as
              implausible for human audit but cannot block or permit a closure.
            </dd>
          </dl>
          <p className="note">
            Every agent has a complete deterministic core, so the system
            degrades to "slightly less eloquent" without an API key — never to
            "unsafe" and never to "offline". A village health worker's tablet
            does not get to depend on an API being up.
          </p>
        </Card>

        <Card
          title="Model usage in this session"
          sub="Published so the cost story is honest: bulk planning never calls a model."
        >
          {usage && (
            <dl className="kv">
              <dt>Model available</dt>
              <dd>{usage.enabled ? (usage.model ?? "yes") : "no — deterministic only"}</dd>
              <dt>Calls made</dt>
              <dd>{usage.calls}</dd>
              <dt>Input tokens</dt>
              <dd>{usage.input_tokens}</dd>
              <dt>Output tokens</dt>
              <dd>{usage.output_tokens}</dd>
              <dt>Deterministic fallbacks</dt>
              <dd>{usage.deterministic_fallbacks}</dd>
            </dl>
          )}
          <p className="note">{usage?.note}</p>
          <p className="note">
            <strong>Why this matters for scale.</strong> A block of 200,000
            people cannot afford a model call per follow-up, and this design
            does not require one. The optimiser plans thousands of obligations
            per second; the model is spent only on the handful of cases a human
            will actually read — a plan rationale, a dialect script, a brief for
            a medical officer.
          </p>
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card
          title={`Published sources (${published.length})`}
          sub="These set the shape of the simulated district: prevalence, follow-up completion, wages, distances."
        >
          <DataTable
            rows={published}
            columns={[
              { head: "Constant", cell: (row) => titleCase(row.constant) },
              { head: "Value", cell: (row) => row.value },
              {
                head: "Source",
                cell: (row) => (
                  <span style={{ whiteSpace: "normal", fontSize: 12 }}>
                    {row.source}
                    {row.note && (
                      <em
                        style={{
                          display: "block",
                          color: "var(--text-muted)",
                        }}
                      >
                        {row.note}
                      </em>
                    )}
                  </span>
                ),
              },
            ]}
          />
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card
          title={`Assumptions (${assumed.length})`}
          sub="The parameters no published Indian dataset gave us — chiefly the weights in the attendance model. Listed here rather than hidden, because these are the numbers worth arguing with."
        >
          <DataTable
            rows={assumed}
            columns={[
              { head: "Parameter", cell: (row) => titleCase(row.constant) },
              { head: "Value", cell: (row) => row.value },
              {
                head: "Why this value",
                cell: (row) => (
                  <span style={{ whiteSpace: "normal", fontSize: 12 }}>
                    {row.note}
                  </span>
                ),
              },
            ]}
            caption="The aggregate behaviour is anchored to published statistics by a test that fails the build if the simulated cascade drifts; these individual weights are a transparent modelling choice."
          />
        </Card>
      </div>

      <div style={{ marginTop: 16 }} className="grid split">
        <Card
          title="Clinical deadlines"
          sub="Days from an abnormal result existing to action ceasing to be timely. Drawn from programme operational guidelines rather than invented."
        >
          <DataTable
            rows={Object.entries(data.clinical_deadlines_days).sort(
              (a, b) => a[1] - b[1],
            )}
            columns={[
              { head: "Condition", cell: ([key]) => titleCase(key) },
              { head: "Days", cell: ([, value]) => String(value) },
            ]}
          />
        </Card>
        <Card
          title="Severity weights"
          sub="Expected healthy life-years lost if the obligation is never discharged. Used to rank the queue, so that forty untreated TB cases outrank four hundred overdue BP rechecks."
        >
          <DataTable
            rows={Object.entries(data.severity_weights_healthy_years).sort(
              (a, b) => b[1] - a[1],
            )}
            columns={[
              { head: "Condition", cell: ([key]) => titleCase(key) },
              { head: "Healthy years", cell: ([, value]) => String(value) },
            ]}
          />
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <Card title="Limits of this work — stated plainly">
          <ul style={{ fontSize: 13.3, paddingLeft: 18, margin: 0 }}>
            <li style={{ marginBottom: 6 }}>
              <strong>The district is simulated.</strong> Nothing here
              describes a real person or place. The behaviour is calibrated to
              published national statistics, which is not the same as being
              validated against a real block's records.
            </li>
            <li style={{ marginBottom: 6 }}>
              <strong>The attendance model is not fitted.</strong> Its weights
              are assumptions chosen so the aggregate cascade reproduces
              published completion rates. A real deployment would refit them on
              its own data within a month, and the code is structured so that
              is a config change rather than a rewrite.
            </li>
            <li style={{ marginBottom: 6 }}>
              <strong>The vernacular copy needs native review.</strong>{" "}
              Machine-written health messaging in somebody's mother tongue is
              how you destroy trust in a programme. Every generated script is
              flagged for sign-off, and only Hindi and Bhojpuri have
              hand-written copy so far.
            </li>
            <li style={{ marginBottom: 6 }}>
              <strong>No real telephony or health-record integration.</strong>{" "}
              The outreach artefacts are generated and inspectable but not
              dialled. The data model is shaped to HL7 FHIR R4 so an
              ABDM-compliant record system is an adapter rather than a
              migration, but that adapter is not written.
            </li>
            <li>
              <strong>Savings are modelled, not measured.</strong> Every
              rupee figure on this site is a prediction from the cost model
              against a counterfactual referral, recorded in the ledger
              before any outcome is known. They are honest predictions; they
              are not yet evidence of realised savings, and the ledger is
              designed so that distinction stays visible.
            </li>
          </ul>
        </Card>
      </div>
    </>
  );
}
