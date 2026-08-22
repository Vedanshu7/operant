// Hand-written contract for the Operant API (base /api/v1).
// Replaced by the generated src/api/schema.d.ts once the backend publishes openapi.json.

export type RunKind = "discovery" | "replay";

export type RunStatus =
  | "queued"
  | "waiting_driver"
  | "running"
  | "waiting_approval"
  | "waiting_intervention"
  | "waiting_clarification"
  | "succeeded"
  | "business_outcome"
  | "escalated"
  | "failed"
  | "cancelled";

export interface RunSummary {
  id: string;
  kind: RunKind;
  status: RunStatus;
  goal: string | null;
  capability_id: string | null;
  vendor_id: string | null;
  profile_id: string | null;
  tenant: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ReplayFailure {
  at_edge: string;
  failure_class: string;
  expected: string;
  observed: string;
  evidence_refs: string[];
}

export type ReplayResult =
  | { status: "success"; outputs: Record<string, string> }
  | { status: "business_outcome"; outcome: string; detail: string }
  | { status: "escalated"; intervention_id: string; resolution: string }
  | { status: "failure"; failure: ReplayFailure };

export interface DiscoveryOutcome {
  capability_id: string;
  graph_version: number;
  inputs: string[];
  outputs: string[];
}

export interface RunDetail extends RunSummary {
  inputs: Record<string, string>;
  result: ReplayResult | DiscoveryOutcome | null;
  error: string | null;
  evidence_dir: string | null;
  pending_approval: Approval | null;
  pending_intervention: Intervention | null;
  pending_clarification: Clarification | null;
  lease_position: number | null;
}

export type ApprovalKind = "scope" | "mutating" | "sensitive_fill" | "sensitive_export";
export type ApprovalStatus = "pending" | "approved" | "denied" | "timed_out";
export type RememberScope = "once" | "process";

export interface ProposedGrant {
  kind: "app" | "url";
  pattern: string;
}

export interface Approval {
  id: string;
  run_id: string;
  kind: ApprovalKind;
  summary: string;
  step: string | null;
  action_kind: string;
  app: string | null;
  details: Record<string, string>;
  proposed_grants: ProposedGrant[];
  status: ApprovalStatus;
  decided_by: string | null;
  remember: RememberScope | null;
  note: string | null;
  raised_at: string;
  decided_at: string | null;
}

export type InterventionState = "paused" | "human" | "resumed" | "abandoned" | "timed_out";

export interface Intervention {
  id: string;
  run_id: string;
  reason: string;
  page_title: string | null;
  edge_id: string | null;
  screenshot_file: string | null;
  state: InterventionState;
  human_actions: string[];
  note: string | null;
  raised_at: string;
  taken_at: string | null;
  resolved_at: string | null;
}

export interface Clarification {
  id: string;
  run_id: string;
  question: string;
  answer: string | null;
  status: "pending" | "answered" | "timed_out";
  raised_at: string;
  answered_at: string | null;
}

export interface CredentialRequest {
  request_id: string;
  name: string;
  reason: string;
}

export interface SseEnvelope {
  run_id: string;
  seq: number;
  at: string;
  type: string;
  summary: string;
  data: Record<string, unknown>;
  run_status: RunStatus;
  screenshot: string | null;
}

export type IoType = "string" | "number" | "boolean";
export type DataClass = "none" | "pii" | "financial" | "credential";

export interface IoField {
  type: IoType;
  description: string;
  required: boolean;
  sensitive: boolean;
  data_class: DataClass;
}

export interface Stability {
  runs: number;
  successes: number;
  last_run_at: string | null;
}

export interface StabilityGate {
  min_runs: number;
  min_success_rate: number;
  passes: boolean;
}

export interface CapabilitySummary {
  id: string;
  name: string;
  description: string;
  vendor_id: string;
  version: number;
  graph_version: number;
  status: "draft" | "approved";
  stability: Stability;
  gate: StabilityGate;
}

export interface TenantBinding {
  base_url: string;
  entry_path: string;
  secret_refs: Record<string, string>;
}

export interface Provenance {
  discovery_run_id: string;
  model: string;
  recorded_at: string;
  goal: string;
}

export interface CapabilityDetail extends CapabilitySummary {
  inputs: Record<string, IoField>;
  outputs: Record<string, { description: string; data_class: string }>;
  start_node: string;
  goal_node: string;
  compiled_path: string[];
  tenants: Record<string, TenantBinding>;
  default_tenant: string;
  provenance: Provenance;
}

export interface ProfileSummary {
  id: string;
  vendor_id: string;
  app_name: string;
  tenants: string[];
}

export type SensitiveFillMode = "literals" | "always" | "off";

export interface ApprovalPolicy {
  mutating: boolean;
  sensitive_fill: SensitiveFillMode;
  sensitive_export: boolean;
  sensitive_field_patterns: string[];
}

export interface Policy {
  allowed_apps: string[];
  allowed_url_patterns: string[];
  allowed_action_kinds: string[];
  mutating_control_patterns: string[];
  approval: ApprovalPolicy;
}

export interface AppProfile {
  vendor_id: string;
  app_name: string;
  window_title_pattern: string;
  default_tenant: string;
  tenants: Record<string, TenantBinding>;
  policy: Policy;
}

export type SecretBackend = "env" | "keychain";

export interface SecretRef {
  name: string;
  backend: SecretBackend;
  locator: string;
  description: string;
  present: boolean;
  last_checked_at: string | null;
}

export type EvidenceFileKind = "png" | "jsonl" | "log" | "other";

export interface EvidenceFile {
  path: string;
  size: number;
  kind: EvidenceFileKind;
}

export interface EvidenceListing {
  files: EvidenceFile[];
}

export interface Health {
  ok: boolean;
  version: string;
}

export interface DoctorCheck {
  name: string;
  status: "ok" | "warn" | "fail";
  detail: string;
}

export interface DoctorReport {
  checks: DoctorCheck[];
}

export interface RunList {
  items: RunSummary[];
  next_cursor: string | null;
}

export interface DiscoveryRequest {
  goal: string;
  capability_id: string;
  name?: string;
  profile_id: string | null;
  tenant?: string;
  inputs: Record<string, string>;
  screenshots?: boolean;
  capture?: boolean;
}

export interface ReplayRequest {
  capability_id: string;
  tenant?: string;
  inputs: Record<string, string>;
  inject_session_expiry_before?: string;
  fresh_session?: boolean;
}

export interface ApprovalDecision {
  approved: boolean;
  remember: RememberScope;
  note?: string;
}

export interface NoteBody {
  note?: string;
}

export interface ClarificationAnswer {
  answer: string;
}

export interface CredentialAnswer {
  value?: string;
  locator?: string;
}

export interface CapabilityApproveBody {
  force?: boolean;
}

export interface CapabilityInvokeBody {
  tenant?: string;
  inputs: Record<string, string>;
}

export interface SecretRefCreate {
  name: string;
  backend: SecretBackend;
  locator: string;
  description?: string;
}

export interface GraphNode {
  id: string;
  [key: string]: unknown;
}

export interface GraphEdge {
  id?: string;
  from?: string;
  to?: string;
  source?: string;
  target?: string;
  [key: string]: unknown;
}

export interface AppGraph {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
  [key: string]: unknown;
}

export interface RunListFilters {
  kind?: RunKind;
  status?: RunStatus;
  capability_id?: string;
  limit?: number;
  cursor?: string;
}
