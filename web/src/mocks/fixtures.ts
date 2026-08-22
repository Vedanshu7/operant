import type {
  AppGraph,
  AppProfile,
  Approval,
  CapabilityDetail,
  Clarification,
  DoctorReport,
  EvidenceListing,
  Intervention,
  ProfileSummary,
  RunDetail,
  SecretRef,
  SseEnvelope,
} from "@/api/types";

const T0 = "2026-08-22T10:00:00Z";

export const approvalFixture: Approval = {
  id: "apr_01",
  run_id: "run_replay_waiting",
  kind: "mutating",
  summary: "Click 'Transfer funds' on Transfer page",
  step: "e7",
  action_kind: "click",
  app: "ParaBank",
  details: {
    control: "button#transfer",
    page: "Transfer Funds",
    from_account: "13344",
    to_account: "13455",
  },
  proposed_grants: [],
  status: "pending",
  decided_by: null,
  remember: null,
  note: null,
  raised_at: "2026-08-22T10:01:10Z",
  decided_at: null,
};

export const scopeApprovalFixture: Approval = {
  ...approvalFixture,
  id: "apr_02",
  run_id: "run_discovery_running",
  kind: "scope",
  summary: "Agent wants to open System Settings",
  action_kind: "open_app",
  app: "System Settings",
  details: { reason: "goal mentions Wi-Fi network name" },
  proposed_grants: [
    { kind: "app", pattern: "com.apple.systempreferences" },
    { kind: "url", pattern: "x-apple.systempreferences:*" },
  ],
};

export const interventionFixture: Intervention = {
  id: "iv_01",
  run_id: "run_replay_escalated",
  reason: "Unexpected dialog: 'Session expired'",
  page_title: "ParaBank - Sign in",
  edge_id: "e3",
  screenshot_file: "shots/0007.png",
  state: "paused",
  human_actions: [],
  note: null,
  raised_at: "2026-08-22T10:02:00Z",
  taken_at: null,
  resolved_at: null,
};

export const clarificationFixture: Clarification = {
  id: "cl_01",
  run_id: "run_discovery_clarify",
  question: "Which account should receive the transfer: Checking (13344) or Savings (13455)?",
  answer: null,
  status: "pending",
  raised_at: "2026-08-22T10:03:00Z",
  answered_at: null,
};

function run(partial: Partial<RunDetail> & Pick<RunDetail, "id" | "kind" | "status">): RunDetail {
  return {
    goal: null,
    capability_id: null,
    vendor_id: "parabank",
    profile_id: "parabank",
    tenant: "demo",
    created_at: T0,
    started_at: "2026-08-22T10:00:05Z",
    finished_at: null,
    inputs: {},
    result: null,
    error: null,
    evidence_dir: null,
    pending_approval: null,
    pending_intervention: null,
    pending_clarification: null,
    lease_position: null,
    ...partial,
  };
}

export const runFixtures: RunDetail[] = [
  run({
    id: "run_discovery_running",
    kind: "discovery",
    status: "running",
    goal: "Transfer $25 from checking to savings and tell me the new balance",
    capability_id: "parabank.transfer",
    inputs: { amount: "25" },
    evidence_dir: "evidence/discovery-20260822-100000",
  }),
  run({
    id: "run_replay_waiting",
    kind: "replay",
    status: "waiting_approval",
    capability_id: "parabank.transfer",
    inputs: { amount: "25", from_account: "13344", to_account: "13455" },
    pending_approval: approvalFixture,
    evidence_dir: "evidence/replay-20260822-100100",
  }),
  run({
    id: "run_replay_escalated",
    kind: "replay",
    status: "waiting_intervention",
    capability_id: "parabank.transfer",
    inputs: { amount: "50", from_account: "13344", to_account: "13455" },
    pending_intervention: interventionFixture,
    evidence_dir: "evidence/replay-20260822-100200",
  }),
  run({
    id: "run_discovery_clarify",
    kind: "discovery",
    status: "waiting_clarification",
    goal: "Move some money to the other account",
    capability_id: "parabank.move-money",
    pending_clarification: clarificationFixture,
  }),
  run({
    id: "run_queued",
    kind: "replay",
    status: "waiting_driver",
    capability_id: "parabank.transfer",
    started_at: null,
    lease_position: 2,
    inputs: { amount: "10", from_account: "13344", to_account: "13455" },
  }),
  run({
    id: "run_replay_ok",
    kind: "replay",
    status: "succeeded",
    capability_id: "parabank.transfer",
    created_at: "2026-08-22T09:00:00Z",
    started_at: "2026-08-22T09:00:03Z",
    finished_at: "2026-08-22T09:00:41Z",
    inputs: { amount: "25", from_account: "13344", to_account: "13455" },
    result: { status: "success", outputs: { new_balance: "$1,234.56", confirmation: "TX-88213" } },
    evidence_dir: "evidence/replay-20260822-090000",
  }),
  run({
    id: "run_replay_outcome",
    kind: "replay",
    status: "business_outcome",
    capability_id: "parabank.transfer",
    created_at: "2026-08-22T08:30:00Z",
    started_at: "2026-08-22T08:30:02Z",
    finished_at: "2026-08-22T08:30:30Z",
    result: {
      status: "business_outcome",
      outcome: "insufficient_funds",
      detail: "Account 13344 balance $12.00 is below the requested $25.00",
    },
  }),
  run({
    id: "run_replay_failed",
    kind: "replay",
    status: "failed",
    capability_id: "parabank.transfer",
    created_at: "2026-08-22T08:00:00Z",
    started_at: "2026-08-22T08:00:02Z",
    finished_at: "2026-08-22T08:00:19Z",
    evidence_dir: "evidence/replay-20260822-080000",
    result: {
      status: "failure",
      failure: {
        at_edge: "e5",
        failure_class: "element_not_found",
        expected: "button 'Transfer' on page 'Transfer Funds'",
        observed: "page 'Error - ParaBank' with no transfer button",
        evidence_refs: ["shots/0005.png", "run-log.jsonl"],
      },
    },
  }),
  run({
    id: "run_discovery_done",
    kind: "discovery",
    status: "succeeded",
    goal: "Log in and export the last statement as PDF",
    capability_id: "parabank.export-statement",
    created_at: "2026-08-21T17:00:00Z",
    started_at: "2026-08-21T17:00:04Z",
    finished_at: "2026-08-21T17:03:12Z",
    evidence_dir: "evidence/discovery-20260821-170000",
    result: {
      capability_id: "parabank.export-statement",
      graph_version: 3,
      inputs: ["account_id"],
      outputs: ["statement_path"],
    },
  }),
];

export const capabilityFixtures: CapabilityDetail[] = [
  {
    id: "parabank.transfer",
    name: "Transfer funds",
    description: "Moves an amount between two accounts and returns the new balance.",
    vendor_id: "parabank",
    version: 2,
    graph_version: 5,
    status: "draft",
    stability: { runs: 7, successes: 6, last_run_at: "2026-08-22T09:00:41Z" },
    gate: { min_runs: 10, min_success_rate: 0.9, passes: false },
    inputs: {
      amount: {
        type: "number",
        description: "Amount in USD",
        required: true,
        sensitive: false,
        data_class: "financial",
      },
      from_account: {
        type: "string",
        description: "Source account number",
        required: true,
        sensitive: true,
        data_class: "financial",
      },
      to_account: {
        type: "string",
        description: "Destination account number",
        required: true,
        sensitive: true,
        data_class: "financial",
      },
      confirm_email: {
        type: "boolean",
        description: "Send confirmation email",
        required: false,
        sensitive: false,
        data_class: "none",
      },
    },
    outputs: {
      new_balance: {
        description: "Balance of the source account after transfer",
        data_class: "financial",
      },
      confirmation: { description: "Transaction reference", data_class: "none" },
    },
    start_node: "n_login",
    goal_node: "n_transfer_done",
    compiled_path: ["n_login", "n_home", "n_transfer_form", "n_transfer_done"],
    tenants: {
      demo: {
        base_url: "https://parabank.parasoft.com",
        entry_path: "/parabank/index.htm",
        secret_refs: { username: "parabank_user", password: "parabank_pass" },
      },
    },
    default_tenant: "demo",
    provenance: {
      discovery_run_id: "run_discovery_done",
      model: "claude-sonnet-4-5",
      recorded_at: "2026-08-21T17:03:12Z",
      goal: "Transfer $25 from checking to savings and tell me the new balance",
    },
  },
  {
    id: "parabank.export-statement",
    name: "Export statement",
    description: "Downloads the latest account statement as PDF.",
    vendor_id: "parabank",
    version: 1,
    graph_version: 3,
    status: "approved",
    stability: { runs: 14, successes: 14, last_run_at: "2026-08-21T17:03:12Z" },
    gate: { min_runs: 10, min_success_rate: 0.9, passes: true },
    inputs: {
      account_id: {
        type: "string",
        description: "Account to export",
        required: true,
        sensitive: false,
        data_class: "financial",
      },
    },
    outputs: { statement_path: { description: "Saved PDF path", data_class: "financial" } },
    start_node: "n_login",
    goal_node: "n_statement_saved",
    compiled_path: ["n_login", "n_home", "n_accounts", "n_statement_saved"],
    tenants: {
      demo: {
        base_url: "https://parabank.parasoft.com",
        entry_path: "/parabank/index.htm",
        secret_refs: { username: "parabank_user", password: "parabank_pass" },
      },
    },
    default_tenant: "demo",
    provenance: {
      discovery_run_id: "run_discovery_done",
      model: "claude-sonnet-4-5",
      recorded_at: "2026-08-21T17:03:12Z",
      goal: "Log in and export the last statement as PDF",
    },
  },
];

export const graphFixture: AppGraph = {
  nodes: [
    { id: "n_login", title: "Sign in", url: "/parabank/index.htm" },
    { id: "n_home", title: "Accounts Overview" },
    { id: "n_transfer_form", title: "Transfer Funds" },
    { id: "n_transfer_done", title: "Transfer Complete" },
  ],
  edges: [
    { id: "e1", from: "n_login", to: "n_home", action: "click", target: "input[type=submit]" },
    {
      id: "e2",
      from: "n_home",
      to: "n_transfer_form",
      action: "click",
      target: "a[href*=transfer]",
    },
    {
      id: "e7",
      from: "n_transfer_form",
      to: "n_transfer_done",
      action: "click",
      target: "button#transfer",
    },
  ],
};

export const profileFixtures: Record<string, AppProfile> = {
  parabank: {
    vendor_id: "parabank",
    app_name: "ParaBank",
    window_title_pattern: "ParaBank.*",
    default_tenant: "demo",
    tenants: {
      demo: {
        base_url: "https://parabank.parasoft.com",
        entry_path: "/parabank/index.htm",
        secret_refs: { username: "parabank_user", password: "parabank_pass" },
      },
      staging: {
        base_url: "https://staging.parabank.example",
        entry_path: "/",
        secret_refs: { username: "parabank_staging_user", password: "parabank_staging_pass" },
      },
    },
    policy: {
      allowed_apps: ["Google Chrome", "Safari"],
      allowed_url_patterns: [
        "https://parabank.parasoft.com/*",
        "https://staging.parabank.example/*",
      ],
      allowed_action_kinds: ["click", "type", "select", "scroll", "navigate"],
      mutating_control_patterns: ["button#transfer", "input[value='Pay']"],
      approval: {
        mutating: true,
        sensitive_fill: "literals",
        sensitive_export: true,
        sensitive_field_patterns: ["password", "ssn", "account"],
      },
    },
  },
  "system-settings": {
    vendor_id: "apple",
    app_name: "System Settings",
    window_title_pattern: "System Settings",
    default_tenant: "local",
    tenants: { local: { base_url: "", entry_path: "", secret_refs: {} } },
    policy: {
      allowed_apps: ["System Settings"],
      allowed_url_patterns: [],
      allowed_action_kinds: ["click", "read"],
      mutating_control_patterns: [],
      approval: {
        mutating: true,
        sensitive_fill: "always",
        sensitive_export: false,
        sensitive_field_patterns: [],
      },
    },
  },
};

export function profileSummaries(): ProfileSummary[] {
  return Object.entries(profileFixtures).map(([id, p]) => ({
    id,
    vendor_id: p.vendor_id,
    app_name: p.app_name,
    tenants: Object.keys(p.tenants),
  }));
}

export const secretRefFixtures: SecretRef[] = [
  {
    name: "parabank_user",
    backend: "env",
    locator: "PARABANK_USER",
    description: "Demo login name",
    present: true,
    last_checked_at: "2026-08-22T09:59:00Z",
  },
  {
    name: "parabank_pass",
    backend: "keychain",
    locator: "operant/parabank/password",
    description: "Demo login password",
    present: true,
    last_checked_at: "2026-08-22T09:59:00Z",
  },
  {
    name: "parabank_staging_user",
    backend: "env",
    locator: "PARABANK_STAGING_USER",
    description: "",
    present: false,
    last_checked_at: null,
  },
  {
    name: "parabank_staging_pass",
    backend: "keychain",
    locator: "operant/parabank-staging/password",
    description: "",
    present: false,
    last_checked_at: null,
  },
];

export const evidenceFixture: EvidenceListing = {
  files: [
    { path: "run-log.jsonl", size: 18233, kind: "jsonl" },
    { path: "driver.log", size: 4021, kind: "log" },
    { path: "shots/0001.png", size: 180233, kind: "png" },
    { path: "shots/0005.png", size: 172211, kind: "png" },
    { path: "shots/0007.png", size: 169877, kind: "png" },
    { path: "capability.json", size: 2210, kind: "other" },
  ],
};

export const doctorFixture: DoctorReport = {
  checks: [
    { name: "driver", status: "ok", detail: "macOS driver reachable at 127.0.0.1:7081" },
    { name: "accessibility", status: "ok", detail: "Accessibility permission granted" },
    {
      name: "screen_recording",
      status: "warn",
      detail: "Screen Recording not granted; screenshots disabled",
    },
    { name: "llm", status: "ok", detail: "model claude-sonnet-4-5 responds" },
  ],
};

export function scriptedEvents(runId: string): SseEnvelope[] {
  const base = (
    seq: number,
    type: string,
    summary: string,
    extra: Partial<SseEnvelope> = {},
  ): SseEnvelope => ({
    run_id: runId,
    seq,
    at: new Date(Date.parse(T0) + seq * 1500).toISOString(),
    type,
    summary,
    data: {},
    run_status: "running",
    screenshot: null,
    ...extra,
  });
  return [
    base(1, "run_status", "Run started", { data: { status: "running" } }),
    base(2, "navigate", "Open https://parabank.parasoft.com/parabank/index.htm", {
      data: { url: "https://parabank.parasoft.com/parabank/index.htm" },
    }),
    base(3, "screenshot_saved", "Screenshot shots/0001.png", {
      data: { file: "shots/0001.png" },
      screenshot: "shots/0001.png",
    }),
    base(4, "fill", "Fill username", {
      data: { control: "input[name=username]", source: "secret:parabank_user" },
    }),
    base(5, "heartbeat", "", {}),
    base(6, "approval_requested", "Approval requested: click 'Transfer funds'", {
      data: { approval: { ...approvalFixture, run_id: runId } },
      run_status: "waiting_approval",
    }),
    base(7, "approval_resolved", "Approved once by operator", {
      data: { approval_id: approvalFixture.id, approved: true, remember: "once" },
    }),
    base(8, "click", "Click button#transfer", { data: { control: "button#transfer" } }),
    base(9, "clarify", "Agent asks a question", {
      data: { clarification: { ...clarificationFixture, run_id: runId } },
      run_status: "waiting_clarification",
    }),
    base(10, "clarification_answered", "Answer: Savings (13455)", {
      data: { answer: "Savings (13455)" },
    }),
    base(11, "escalation_raised", "Unexpected dialog, handing to human", {
      data: { intervention: { ...interventionFixture, run_id: runId } },
      run_status: "waiting_intervention",
    }),
    base(12, "control_transition", "Human took control", {
      data: {
        intervention: { ...interventionFixture, run_id: runId, state: "human", taken_at: T0 },
      },
      run_status: "waiting_intervention",
    }),
    base(13, "control_transition", "Control handed back", {
      data: {
        intervention: {
          ...interventionFixture,
          run_id: runId,
          state: "resumed",
          human_actions: ["click Sign in", "type ****"],
        },
      },
    }),
    base(14, "screenshot_saved", "Screenshot shots/0007.png", {
      data: { file: "shots/0007.png" },
      screenshot: "shots/0007.png",
    }),
    base(15, "goal_complete", "Goal complete", { data: { outputs: { new_balance: "$1,234.56" } } }),
    base(16, "replay_finished", "Run finished: succeeded", {
      data: { status: "succeeded" },
      run_status: "succeeded",
    }),
  ];
}
