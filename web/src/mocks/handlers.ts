import { http, HttpResponse, type PathParams } from "msw";

import type {
  AppProfile,
  Approval,
  ApprovalDecision,
  CapabilityApproveBody,
  CapabilityInvokeBody,
  Clarification,
  ClarificationAnswer,
  DiscoveryRequest,
  Intervention,
  NoteBody,
  ReplayRequest,
  RunDetail,
  RunStatus,
  RunSummary,
  SecretRef,
  SecretRefCreate,
  TenantBinding,
} from "@/api/types";

import {
  approvalFixture,
  capabilityFixtures,
  clarificationFixture,
  doctorFixture,
  evidenceFixture,
  graphFixture,
  interventionFixture,
  profileFixtures,
  profileSummaries,
  runFixtures,
  scopeApprovalFixture,
  scriptedEvents,
  secretRefFixtures,
} from "./fixtures";
import { sseStream } from "./sse";

const BASE = "/api/v1";

interface MockState {
  runs: RunDetail[];
  approvals: Approval[];
  interventions: Intervention[];
  clarifications: Clarification[];
  capabilities: typeof capabilityFixtures;
  profiles: Record<string, AppProfile>;
  secrets: SecretRef[];
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function freshState(): MockState {
  return {
    runs: clone(runFixtures),
    approvals: clone([approvalFixture, scopeApprovalFixture]),
    interventions: clone([interventionFixture]),
    clarifications: clone([clarificationFixture]),
    capabilities: clone(capabilityFixtures),
    profiles: clone(profileFixtures),
    secrets: clone(secretRefFixtures),
  };
}

export let state: MockState = freshState();

export function resetMockState(): void {
  state = freshState();
}

const PNG_1x1 = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  ),
  (c) => c.charCodeAt(0),
);

function notFound(detail: string): Response {
  return HttpResponse.json({ detail }, { status: 404 });
}

function newRun(partial: Partial<RunDetail> & Pick<RunDetail, "kind">): RunDetail {
  const id = `run_${Math.random().toString(36).slice(2, 8)}`;
  const run: RunDetail = {
    id,
    status: "queued",
    goal: null,
    capability_id: null,
    vendor_id: null,
    profile_id: null,
    tenant: null,
    created_at: new Date().toISOString(),
    started_at: null,
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
  state.runs.unshift(run);
  return run;
}

function summary(run: RunDetail): RunSummary {
  return {
    id: run.id,
    kind: run.kind,
    status: run.status,
    goal: run.goal,
    capability_id: run.capability_id,
    vendor_id: run.vendor_id,
    profile_id: run.profile_id,
    tenant: run.tenant,
    created_at: run.created_at,
    started_at: run.started_at,
    finished_at: run.finished_at,
  };
}

function setRunStatus(id: string, status: RunStatus): void {
  const run = state.runs.find((r) => r.id === id);
  if (run) run.status = status;
}

export const handlers = [
  http.get(`${BASE}/health`, () => HttpResponse.json({ ok: true, version: "0.7.0-mock" })),
  http.get(`${BASE}/doctor`, () => HttpResponse.json(doctorFixture)),

  http.get(`${BASE}/runs`, ({ request }) => {
    const url = new URL(request.url);
    const kind = url.searchParams.get("kind");
    const status = url.searchParams.get("status");
    const cap = url.searchParams.get("capability_id");
    const items = state.runs
      .filter((r) => !kind || r.kind === kind)
      .filter((r) => !status || r.status === status)
      .filter((r) => !cap || r.capability_id === cap)
      .map(summary);
    return HttpResponse.json({ items, next_cursor: null });
  }),
  http.post(`${BASE}/runs/discovery`, async ({ request }) => {
    const body = (await request.json()) as DiscoveryRequest;
    const run = newRun({
      kind: "discovery",
      status: "running",
      goal: body.goal,
      capability_id: body.capability_id,
      profile_id: body.profile_id,
      tenant: body.tenant ?? null,
      inputs: body.inputs,
      started_at: new Date().toISOString(),
    });
    return HttpResponse.json(summary(run), { status: 201 });
  }),
  http.post(`${BASE}/runs/replay`, async ({ request }) => {
    const body = (await request.json()) as ReplayRequest;
    const run = newRun({
      kind: "replay",
      status: "running",
      capability_id: body.capability_id,
      tenant: body.tenant ?? null,
      inputs: body.inputs,
      started_at: new Date().toISOString(),
    });
    return HttpResponse.json(summary(run), { status: 201 });
  }),
  http.get<PathParams<"id">>(`${BASE}/runs/:id`, ({ params }) => {
    const run = state.runs.find((r) => r.id === params.id);
    return run ? HttpResponse.json(run) : notFound("run not found");
  }),
  http.post<PathParams<"id">>(`${BASE}/runs/:id/cancel`, ({ params }) => {
    const run = state.runs.find((r) => r.id === params.id);
    if (!run) return notFound("run not found");
    run.status = "cancelled";
    run.finished_at = new Date().toISOString();
    return HttpResponse.json(summary(run));
  }),
  http.get<PathParams<"id">>(`${BASE}/runs/:id/events`, ({ params, request }) => {
    const after = Number(new URL(request.url).searchParams.get("after") ?? "0");
    const events = scriptedEvents(String(params.id)).filter((e) => e.seq > after);
    return new HttpResponse(sseStream(events, 1500), {
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
    });
  }),
  http.get(`${BASE}/runs/:id/screenshot`, () =>
    HttpResponse.arrayBuffer(PNG_1x1.buffer, { headers: { "Content-Type": "image/png" } }),
  ),

  http.get(`${BASE}/approvals`, ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    return HttpResponse.json(state.approvals.filter((a) => !status || a.status === status));
  }),
  http.post<PathParams<"id">>(`${BASE}/approvals/:id`, async ({ params, request }) => {
    const body = (await request.json()) as ApprovalDecision;
    const approval = state.approvals.find((a) => a.id === params.id);
    if (!approval) return notFound("approval not found");
    approval.status = body.approved ? "approved" : "denied";
    approval.remember = body.remember;
    approval.note = body.note ?? null;
    approval.decided_by = "operator";
    approval.decided_at = new Date().toISOString();
    const run = state.runs.find((r) => r.id === approval.run_id);
    if (run) {
      run.pending_approval = null;
      run.status = body.approved ? "running" : "failed";
    }
    return HttpResponse.json(approval);
  }),

  http.post<PathParams<"id" | "action">>(
    `${BASE}/interventions/:id/:action`,
    async ({ params, request }) => {
      const body = (await request.json().catch(() => ({}))) as NoteBody;
      const iv = state.interventions.find((i) => i.id === params.id);
      if (!iv) return notFound("intervention not found");
      const now = new Date().toISOString();
      if (params.action === "take") {
        iv.state = "human";
        iv.taken_at = now;
      } else if (params.action === "handback") {
        iv.state = "resumed";
        iv.resolved_at = now;
        iv.human_actions = [...iv.human_actions, "click Sign in", "type ****"];
        setRunStatus(iv.run_id, "running");
      } else if (params.action === "abandon") {
        iv.state = "abandoned";
        iv.resolved_at = now;
        setRunStatus(iv.run_id, "escalated");
      } else {
        return notFound("unknown action");
      }
      iv.note = body.note ?? iv.note;
      const run = state.runs.find((r) => r.id === iv.run_id);
      if (run) run.pending_intervention = iv.state === "human" ? iv : null;
      return HttpResponse.json(iv);
    },
  ),

  http.post<PathParams<"id">>(`${BASE}/clarifications/:id`, async ({ params, request }) => {
    const body = (await request.json()) as ClarificationAnswer;
    const c = state.clarifications.find((x) => x.id === params.id);
    if (!c) return notFound("clarification not found");
    c.answer = body.answer;
    c.status = "answered";
    c.answered_at = new Date().toISOString();
    const run = state.runs.find((r) => r.id === c.run_id);
    if (run) {
      run.pending_clarification = null;
      run.status = "running";
    }
    return HttpResponse.json(c);
  }),

  http.get(`${BASE}/capabilities`, () =>
    HttpResponse.json(
      state.capabilities.map(
        ({
          id,
          name,
          description,
          vendor_id,
          version,
          graph_version,
          status,
          stability,
          gate,
        }) => ({
          id,
          name,
          description,
          vendor_id,
          version,
          graph_version,
          status,
          stability,
          gate,
        }),
      ),
    ),
  ),
  http.get<PathParams<"id">>(`${BASE}/capabilities/:id`, ({ params }) => {
    const cap = state.capabilities.find((c) => c.id === params.id);
    return cap ? HttpResponse.json(cap) : notFound("capability not found");
  }),
  http.get(`${BASE}/capabilities/:id/graph`, () => HttpResponse.json(graphFixture)),
  http.post<PathParams<"id">>(`${BASE}/capabilities/:id/approve`, async ({ params, request }) => {
    const body = (await request.json().catch(() => ({}))) as CapabilityApproveBody;
    const cap = state.capabilities.find((c) => c.id === params.id);
    if (!cap) return notFound("capability not found");
    if (!cap.gate.passes && !body.force) {
      return HttpResponse.json(
        {
          detail: `Stability gate not met: ${cap.stability.successes}/${cap.stability.runs} runs, need ${cap.gate.min_runs} runs at ${Math.round(cap.gate.min_success_rate * 100)}%`,
        },
        { status: 409 },
      );
    }
    cap.status = "approved";
    return HttpResponse.json(cap);
  }),
  http.post<PathParams<"id">>(`${BASE}/capabilities/:id/invoke`, async ({ params, request }) => {
    const body = (await request.json()) as CapabilityInvokeBody;
    const run = newRun({
      kind: "replay",
      status: "queued",
      capability_id: String(params.id),
      tenant: body.tenant ?? null,
      inputs: body.inputs,
      lease_position: 1,
    });
    return HttpResponse.json(summary(run), { status: 201 });
  }),

  http.get(`${BASE}/profiles`, () => HttpResponse.json(profileSummaries())),
  http.get<PathParams<"id">>(`${BASE}/profiles/:id`, ({ params }) => {
    const p = state.profiles[String(params.id)];
    return p ? HttpResponse.json(p) : notFound("profile not found");
  }),
  http.put<PathParams<"id">>(`${BASE}/profiles/:id`, async ({ params, request }) => {
    const body = (await request.json()) as AppProfile;
    state.profiles[String(params.id)] = body;
    return HttpResponse.json(body);
  }),
  http.put<PathParams<"id" | "tenant">>(
    `${BASE}/profiles/:id/tenants/:tenant`,
    async ({ params, request }) => {
      const body = (await request.json()) as TenantBinding;
      const p = state.profiles[String(params.id)];
      if (!p) return notFound("profile not found");
      p.tenants[String(params.tenant)] = body;
      return HttpResponse.json(p);
    },
  ),

  http.get(`${BASE}/secrets/refs`, () => HttpResponse.json(state.secrets)),
  http.post(`${BASE}/secrets/refs`, async ({ request }) => {
    const body = (await request.json()) as SecretRefCreate;
    const ref: SecretRef = {
      name: body.name,
      backend: body.backend,
      locator: body.locator,
      description: body.description ?? "",
      present: false,
      last_checked_at: null,
    };
    state.secrets.push(ref);
    return HttpResponse.json(ref, { status: 201 });
  }),
  http.delete<PathParams<"name">>(`${BASE}/secrets/refs/:name`, ({ params }) => {
    state.secrets = state.secrets.filter((s) => s.name !== params.name);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post<PathParams<"name">>(`${BASE}/secrets/refs/:name/check`, ({ params }) => {
    const ref = state.secrets.find((s) => s.name === params.name);
    if (!ref) return notFound("secret ref not found");
    ref.present = ref.backend === "env" ? ref.locator.length > 0 : !ref.name.includes("staging");
    ref.last_checked_at = new Date().toISOString();
    return HttpResponse.json(ref);
  }),

  http.get(`${BASE}/evidence/:runId`, () => HttpResponse.json(evidenceFixture)),
  http.get<PathParams<"runId" | "path">>(
    `${BASE}/evidence/:runId/files/*`,
    ({ params, request }) => {
      const path = decodeURIComponent(new URL(request.url).pathname.split("/files/")[1] ?? "");
      if (path.endsWith(".png")) {
        return HttpResponse.arrayBuffer(PNG_1x1.buffer, {
          headers: { "Content-Type": "image/png" },
        });
      }
      if (path.endsWith(".jsonl")) {
        const lines = scriptedEvents(String(params.runId)).map((e) => JSON.stringify(e));
        return HttpResponse.text(lines.join("\n"), {
          headers: { "Content-Type": "application/x-ndjson" },
        });
      }
      return HttpResponse.text(`mock contents of ${path}\n`);
    },
  ),
];
