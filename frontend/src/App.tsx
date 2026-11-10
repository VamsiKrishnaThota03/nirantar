import { useCallback, useEffect, useState } from "react";
import { api, type Overview } from "./lib/api";
import { compact, dateFull, n, pct } from "./lib/format";
import { AgentTheatre } from "./components/AgentTheatre";
import { DistrictView } from "./components/DistrictView";
import { FieldView } from "./components/FieldView";
import { LedgerView } from "./components/LedgerView";
import { MethodView } from "./components/MethodView";
import { TrialView } from "./components/TrialView";

type Tab = "district" | "agents" | "trial" | "field" | "ledger" | "method";

const TABS: { id: Tab; label: string }[] = [
  { id: "district", label: "The gap" },
  { id: "agents", label: "Watch the agents" },
  { id: "trial", label: "The trial" },
  { id: "field", label: "Field app" },
  { id: "ledger", label: "Impact ledger" },
  { id: "method", label: "Method & sources" },
];

const isTab = (value: string): value is Tab =>
  TABS.some((item) => item.id === value);

export default function App() {
  // Hash routing, so a section can be linked to directly -- useful when
  // pointing someone at the ledger rather than at the front page.
  const [tab, setTab] = useState<Tab>(() => {
    const hash = window.location.hash.replace("#", "");
    return isTab(hash) ? hash : "district";
  });

  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash.replace("#", "");
      if (isTab(hash)) setTab(hash);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const selectTab = useCallback((next: Tab) => {
    setTab(next);
    window.location.hash = next;
  }, []);

  const [theme, setTheme] = useState<"light" | "dark">(() =>
    (localStorage.getItem("nirantar-theme") as "light" | "dark" | null) ??
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );
  const [overview, setOverview] = useState<Overview | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("nirantar-theme", theme);
  }, [theme]);

  const loadOverview = useCallback(async () => {
    try {
      setOverview(await api.overview());
    } catch {
      /* the views surface their own errors */
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview, refreshKey]);

  const bumpRefresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            Nirantar <small>निरंतर · continuity of care</small>
          </div>
          <nav className="tabs" role="tablist" aria-label="Sections">
            {TABS.map((item) => (
              <button
                key={item.id}
                className="tab"
                role="tab"
                aria-selected={tab === item.id}
                onClick={() => selectTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <button
            className="icon-btn"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>
      </header>

      <main className="shell">
        {tab === "district" && (
          <section className="hero">
            <div className="eyebrow">
              Code for a Billion 2026 · Health · Open source
            </div>
            <h1>India screens superbly and follows up terribly.</h1>
            <p className="lede">
              Tens of crores of Indians have been screened for hypertension,
              diabetes and three cancers. Most abnormal results never reach a
              clinician. The gap between <strong>"we found your problem"</strong>{" "}
              and <strong>"we treated your problem"</strong> is where people
              die — and it is not a clinical problem. It is a logistics problem,
              which is exactly what agents are for.
            </p>
            <p className="lede">
              Nirantar treats every un-treated abnormal result as a{" "}
              <strong>care debt</strong>: an obligation the health system owes a
              named person, with a clinical deadline. Five agents work that
              ledger — pricing what a follow-up really costs a daily-wage
              household, finding capacity nobody knew existed, and routing
              around the barrier instead of nagging the patient about it.
              Nothing is closed without evidence, and every closure is signed
              into a ledger anyone can audit.
            </p>
          </section>
        )}

        {overview && (
          <div className="banner" style={{ marginTop: tab === "district" ? 20 : 0 }}>
            <span aria-hidden>ℹ</span>
            <div>
              <strong>This is a demonstration on generated data.</strong>{" "}
              {compact(overview.population_modelled)} fictional residents of{" "}
              {overview.block} block, {overview.district} district, calibrated
              to published Indian health statistics — NFHS-5, the India TB
              Report, National Health Accounts. No real person's health data is
              present anywhere in this system. Model as of{" "}
              {dateFull(overview.as_of)}.{" "}
              {overview.llm_enabled ? (
                <>Claude is connected, so the reasoning agents are live.</>
              ) : (
                <>
                  No model key is configured, so the agents are running on their
                  deterministic cores — which is a supported mode, not a
                  degraded one.
                </>
              )}
            </div>
          </div>
        )}

        {tab === "district" && <DistrictView refreshKey={refreshKey} />}
        {tab === "agents" && <AgentTheatre onLedgerChange={bumpRefresh} />}
        {tab === "trial" && <TrialView />}
        {tab === "field" && <FieldView onLedgerChange={bumpRefresh} />}
        {tab === "ledger" && (
          <LedgerView refreshKey={refreshKey} onLedgerChange={bumpRefresh} />
        )}
        {tab === "method" && <MethodView />}

        <footer className="site">
          <p>
            <strong>Nirantar</strong> — continuity of care for a billion. Built
            for Code for a Billion 2026, the Bharat Agentic-AI Hackathon.
            Licensed Apache-2.0; the data model is shaped to HL7 FHIR R4 so an
            ABDM-compliant record system is an adapter rather than a migration.
          </p>
          {overview && (
            <p>
              Modelling {n(overview.care_debts_total)} care obligations across{" "}
              {compact(overview.population_modelled)} people ·{" "}
              {pct(overview.share_of_population_owed_care, 1)} of the block is
              currently owed care · {n(overview.ledger.ledger_entries)} ledger
              entries.
            </p>
          )}
          <p>
            Health data deserves a real gate. Person-level endpoints here are
            anonymous <em>only</em> because every record is generated; point this
            process at real records and it refuses to start without an identity
            provider configured. See <code>SECURITY.md</code>.
          </p>
        </footer>
      </main>
    </>
  );
}
