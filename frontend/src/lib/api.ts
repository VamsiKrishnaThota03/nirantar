/** Thin API client.
 *
 * Streaming uses `fetch` with a stream reader rather than `EventSource`,
 * because EventSource cannot carry an Authorization header and the agent
 * routes are gated whenever the backend holds real records.
 */

export type Overview = {
  district: string;
  block: string;
  as_of: string;
  population_modelled: number;
  care_debts_total: number;
  care_debts_open: number;
  care_debts_breached: number;
  care_debts_closed: number;
  care_debts_unreachable: number;
  by_status: Record<string, number>;
  healthy_years_at_stake: number;
  people_with_open_debt: number;
  share_of_population_owed_care: number;
  demo_mode: boolean;
  llm_enabled: boolean;
  ledger: LedgerImpact;
};

export type LedgerImpact = {
  debts_closed: number;
  distinct_people_served: number;
  patient_rupees_saved: number;
  patient_travel_km_avoided: number;
  patient_wage_days_saved: number;
  expected_additional_closures_vs_conventional: number;
  closed_by_condition: Record<string, number>;
  ledger_entries: number;
};

export type CascadeStage = {
  stage: string;
  count: number;
  note: string;
  /** False where the people who fall out were screened and found healthy. */
  drop_is_loss?: boolean;
  drop_label?: string;
};
export type AgingBucket = {
  bucket: string;
  count: number;
  healthy_years_at_stake: number;
};
export type ConditionRow = {
  condition: string;
  label: string;
  open: number;
  closed: number;
  breached: number;
  closure_rate: number;
  severity_weight: number;
  deadline_days: number;
  healthy_years_at_stake: number;
};
export type PanchayatRow = {
  panchayat: string;
  population: number;
  open: number;
  breached: number;
  closed: number;
  people_owed_care: number;
  open_per_1000: number;
  healthy_years_at_stake: number;
  next_outreach_visit: string | null;
  days_until_outreach: number | null;
  unstaffed_facilities: string[];
  km_to_district_hospital: number;
};
export type BarrierProfile = {
  sample_size: number;
  population_of_open_debts: number;
  mean_conventional_cost_inr: number;
  mean_conventional_travel_km: number;
  mean_conventional_no_show: number;
  projected_aggregate_cost_inr: number;
  barriers: { barrier: string; count: number; share: number }[];
};
export type SupplyGaps = {
  stockouts: {
    facility: string;
    facility_type: string;
    panchayat: string;
    drug: string;
    units: number;
  }[];
  stockout_count: number;
  unstaffed_facilities: { facility: string; panchayat: string; type: string }[];
  panchayats_without_outreach_14d: string[];
  specialist_slots_next_14d: number;
  specialist_reviews_owed: number;
  specialist_capacity_ratio: number;
  asha_overloaded: {
    asha: string;
    panchayat: string;
    open_tasks: number;
    capacity: number;
  }[];
};
export type WorklistRow = {
  debt_id: string;
  condition: string;
  label: string;
  required_action: string;
  status: string;
  opened_on: string;
  deadline_on: string;
  days_to_deadline: number;
  breached: boolean;
  severity_weight: number;
  person: {
    id: string;
    display_name: string;
    age: number;
    sex: string;
    village: string;
    panchayat: string;
    language: string;
    literacy: string;
    phone_type: string;
    daily_wage_inr: number;
    km_to_district: number;
    is_pregnant: boolean;
  };
};

export type CostBreakdown = {
  wage_loss_days: number;
  wage_loss_inr: number;
  fare_inr: number;
  user_fee_inr: number;
  total_inr: number;
  travel_km: number;
  share_of_daily_wage: number;
};

export type CarePlan = {
  id: string;
  debt_id: string;
  person_id: string;
  strategy: string;
  steps: {
    order: number;
    actor: string;
    action: string;
    where: string;
    on_date: string | null;
  }[];
  cost: CostBreakdown;
  days_to_closure: number;
  predicted_no_show: number;
  outreach_channel: string;
  outreach_language: string;
  asha_id: string | null;
  rationale: string;
  safety_overrides: string[];
  generated_by: "llm" | "deterministic";
  artifacts: {
    channel: string;
    channel_label: string;
    script_language: string;
    outreach_blocked: boolean;
    voice_script: {
      language: string;
      language_code: string;
      script: string;
      english_gloss: string;
      estimated_duration_seconds: number;
      requires_native_review: boolean;
      fell_back_to_hindi: boolean;
      privacy_note: string;
      retry_policy: { attempts: number; spacing_hours: number[]; note: string };
      dtmf: Record<string, string>;
    };
    whatsapp: { body: string; english_gloss: string };
    sms_fallback: { body: string; note: string };
    asha_task_card: Record<string, unknown>;
    stock_reservation: {
      drug: string;
      units: number;
      at: string;
      note: string;
    } | null;
  };
  counterfactual: {
    description: string;
    facility: string;
    cost_inr: number;
    travel_km: number;
    wage_loss_days: number;
    no_show: number;
    days_until_slot: number;
    savings_inr: number;
    travel_km_avoided: number;
    no_show_reduction_pp: number;
  };
};

export type AgentStep = {
  agent: string;
  phase: string;
  started_at: string;
  duration_ms: number;
  summary: string;
  detail: Record<string, any>;
  used_llm: boolean;
};

export type LedgerEntry = {
  seq: number;
  ts: string;
  event_type: string;
  subject: string;
  debt_ref: string;
  payload: Record<string, unknown>;
  payload_digest: string;
  prev_hash: string;
  entry_hash: string;
  signature: string;
  key_id: string;
};

export type LedgerVerify = {
  entries: number;
  valid: boolean;
  head_hash: string;
  key_id: string;
  public_key_ed25519_b64: string;
  problems: { seq: number; problem: string }[];
  verified_at: string;
  how_to_verify_independently: string;
};

export type EscalationBrief = {
  id: string;
  raised_on: string;
  to_role: string;
  panchayat: string | null;
  headline: string;
  brief_markdown: string;
  systemic_cause: string;
  generated_by: string;
  debt_ids: string[];
};

export type Cluster = {
  cause: string;
  cause_label: string;
  panchayat: string;
  count: number;
  breached_count: number;
  people_affected: number;
  healthy_years_at_stake: number;
  highest_risk_score: number;
  conditions: Record<string, number>;
  drugs_implicated: Record<string, number>;
  remedy: string;
  oldest_days_overdue: number;
};

export type CalibrationPayload = {
  note: string;
  assumed_count: number;
  constants: {
    constant: string;
    value: string;
    source: string;
    note: string;
    assumed: string;
  }[];
  clinical_deadlines_days: Record<string, number>;
  severity_weights_healthy_years: Record<string, number>;
};

export type EquityStratum = {
  stratum: string;
  n: number;
  mean_value: number;
  served: number;
  served_rate: number;
};

export type EquityReport = {
  people_owed_care: number;
  people_contacted: number;
  people_served: number;
  overall_served_rate: number;
  denominator: string;
  by_distance: EquityStratum[];
  by_wage: EquityStratum[];
  nearest_over_furthest_ratio: number | null;
  richest_over_poorest_ratio: number | null;
  by_attribute: {
    attribute: string;
    with_n: number;
    with_served_rate: number;
    without_n: number;
    without_served_rate: number;
  }[];
  female_served_rate: number;
  male_served_rate: number;
};

export type ArmSummary = {
  arm: string;
  obligations_closed: number;
  still_open: number;
  past_deadline: number;
  given_up_unreachable: number;
  healthy_years_discharged: number;
  patient_rupees_spent: number;
  patient_travel_km: number;
  contacts_made: number;
  attendances: number;
  attendance_rate: number;
  rupees_per_closure: number;
};

export type BurnDownPoint = {
  day: number;
  on_date: string;
  open: number;
  closed_cumulative: number;
  healthy_years_discharged: number;
  unreachable: number;
};

export type Spread = { min: number; median: number; max: number; mean: number };

export type TrialReport = {
  elapsed_seconds: number;
  design: {
    days: number;
    trials: number;
    population: number;
    seed: number;
    perturbation_scale: number;
    daily_contact_share: number;
    max_attempts: number;
    note: string;
    not_a_claim_of_real_impact: string;
  };
  trials: {
    trial: number;
    truth_coefficients: Record<string, number>;
    status_quo: ArmSummary;
    nirantar: ArmSummary;
    extra_closures: number;
    closure_multiple: number;
    extra_healthy_years: number;
    rupees_per_closure_status_quo: number;
    rupees_per_closure_nirantar: number;
  }[];
  aggregate: {
    closure_multiple: Spread;
    extra_closures: Spread;
    extra_healthy_years: Spread;
    cost_per_closure_ratio: Spread;
    nirantar_better_in_all_trials: boolean;
  };
  burn_down: { status_quo: BurnDownPoint[]; nirantar: BurnDownPoint[] };
  calibration: {
    nirantar: {
      bucket: string;
      n: number;
      predicted_no_show: number;
      realised_no_show: number;
      error: number;
    }[];
    brier_nirantar: number;
    brier_status_quo: number;
    note: string;
  };
  equity: {
    status_quo: EquityReport;
    nirantar: EquityReport;
    nirantar_without_equity_weighting: EquityReport;
    ablation: {
      trial: number;
      with_equity_weighting: Record<string, number>;
      without_equity_weighting: Record<string, number>;
    }[];
    note: string;
    what_we_found: string;
  };
};

export type AshaRow = {
  id: string;
  display_name: string;
  panchayat: string;
  villages: string[];
  languages: string[];
  open_tasks: number;
  weekly_visit_capacity: number;
  obligations_in_her_villages: number;
};

export type AshaObligation = {
  debt_id: string;
  why: string;
  days_to_deadline: number;
  closes_with: string;
  closes_with_plain: string;
  plan: {
    what: string;
    when: string | null;
    accompany: boolean;
    bring: string[];
    say: string | null;
  } | null;
};

/** One household, one walk. Several obligations may sit behind one visit. */
export type AshaVisit = {
  /** Stable identifier: display names are not unique. */
  ref: string;
  who: string;
  age: number;
  sex: string;
  village: string;
  language: string;
  phone: string;
  urgent: boolean;
  obligations: AshaObligation[];
};

export type AshaTaskPayload = {
  asha: { id: string; display_name: string; panchayat: string; villages: string[] };
  as_of: string;
  visits: AshaVisit[];
  transfer: {
    bytes: number;
    visits: number;
    obligations: number;
    bytes_per_visit: number;
    seconds_on_2g: number;
    note: string;
  };
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  cascade: () => request<CascadeStage[]>("/api/cascade"),
  aging: () => request<AgingBucket[]>("/api/aging"),
  conditions: () => request<ConditionRow[]>("/api/conditions"),
  panchayats: () => request<PanchayatRow[]>("/api/panchayats"),
  barriers: () => request<BarrierProfile>("/api/barriers"),
  supplyGaps: () => request<SupplyGaps>("/api/supply-gaps"),
  clusters: () => request<Cluster[]>("/api/escalations/clusters"),
  escalations: () => request<EscalationBrief[]>("/api/escalations"),
  calibration: () => request<CalibrationPayload>("/api/calibration"),
  worklist: (params: { limit?: number; panchayat?: string; condition?: string } = {}) => {
    const search = new URLSearchParams();
    search.set("limit", String(params.limit ?? 30));
    if (params.panchayat) search.set("panchayat", params.panchayat);
    if (params.condition) search.set("condition", params.condition);
    return request<WorklistRow[]>(`/api/worklist?${search}`);
  },
  debt: (id: string) => request<any>(`/api/debts/${id}`),
  closeDebt: (
    id: string,
    body: { kind: string; detail: string; recorded_by: string },
  ) =>
    request<any>(`/api/debts/${id}/close`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  batch: (limit: number) =>
    request<{
      attempted: number;
      planned: number;
      unplannable: number;
      elapsed_seconds: number;
      patient_rupees_saved: number;
      patient_travel_km_avoided: number;
      expected_additional_attendances: number;
      plans_requiring_no_travel: number;
      note: string;
    }>("/api/simulate/batch", {
      method: "POST",
      body: JSON.stringify({ limit, use_llm: false }),
    }),
  runEscalations: (top: number) =>
    request<{ escalations: EscalationBrief[] }>(
      `/api/escalations/run?top=${top}`,
      { method: "POST" },
    ),
  ledgerSummary: () => request<LedgerImpact>("/api/ledger/summary"),
  ledgerEntries: (limit = 40, offset = 0) =>
    request<{ total: number; entries: LedgerEntry[]; privacy_note: string }>(
      `/api/ledger/entries?limit=${limit}&offset=${offset}`,
    ),
  ledgerVerify: () => request<LedgerVerify>("/api/ledger/verify"),
  trial: (body: { days: number; trials: number; perturbation?: number }) =>
    request<TrialReport>("/api/trial", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ashas: () => request<AshaRow[]>("/api/asha"),
  ashaTasks: (id: string) => request<AshaTaskPayload>(`/api/asha/${id}/tasks`),
  llmUsage: () =>
    request<{
      enabled: boolean;
      model: string | null;
      calls: number;
      input_tokens: number;
      output_tokens: number;
      deterministic_fallbacks: number;
      note: string;
    }>("/api/llm/usage"),
};

export type StreamFrame =
  | { type: "run_started"; debt_id: string; person: any; debt: any; at: string }
  | { type: "agent_started"; agent: string; phase: string }
  | { type: "agent_step"; step: AgentStep }
  | {
      type: "run_finished";
      plan: CarePlan | null;
      debt: any;
      no_viable_plan: boolean;
      safety_overrides: string[];
    }
  | { type: "closed"; llm_usage: Record<string, number>; safety_overrides: string[] }
  | { type: "error"; error: string };

/** Streams the agent pipeline, invoking `onFrame` as each stage completes. */
export async function streamPlan(
  debtId: string,
  onFrame: (frame: StreamFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/debts/${debtId}/plan/stream`, { signal });
  if (!response.ok || !response.body) {
    throw new ApiError(
      `Could not start the agent run (${response.status})`,
      response.status,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line.
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onFrame(JSON.parse(line.slice(6)) as StreamFrame);
      } catch {
        /* ignore a partial frame */
      }
    }
  }
}
