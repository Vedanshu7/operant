import { describe, expect, it } from "vitest";

import type { SseEnvelope } from "@/api/types";
import { approvalFixture, clarificationFixture, interventionFixture } from "@/mocks/fixtures";

import { initialRunStreamState, runStreamReducer, type RunStreamState } from "./runStreamReducer";

function ev(seq: number, type: string, extra: Partial<SseEnvelope> = {}): SseEnvelope {
  return {
    run_id: "r1",
    seq,
    at: "2026-08-22T10:00:00Z",
    type,
    summary: type,
    data: {},
    run_status: "running",
    screenshot: null,
    ...extra,
  };
}

function apply(state: RunStreamState, ...events: SseEnvelope[]): RunStreamState {
  return events.reduce((s, e) => runStreamReducer(s, { type: "event", event: e }), state);
}

describe("runStreamReducer", () => {
  it("sets pendingApproval on approval_requested and clears on approval_resolved", () => {
    const requested = apply(
      initialRunStreamState,
      ev(1, "approval_requested", {
        data: { approval: approvalFixture },
        run_status: "waiting_approval",
      }),
    );
    expect(requested.pendingApproval?.id).toBe(approvalFixture.id);
    expect(requested.status).toBe("waiting_approval");
    const resolved = apply(requested, ev(2, "approval_resolved"));
    expect(resolved.pendingApproval).toBeNull();
    expect(resolved.status).toBe("running");
  });

  it("updates status from run_status events and tracks lastSeq", () => {
    const s = apply(
      initialRunStreamState,
      ev(5, "run_status", { run_status: "waiting_driver" }),
      ev(9, "run_status", { run_status: "running" }),
    );
    expect(s.status).toBe("running");
    expect(s.lastSeq).toBe(9);
    expect(s.events).toHaveLength(2);
  });

  it("ignores heartbeats for the timeline but still advances lastSeq", () => {
    const s = apply(initialRunStreamState, ev(3, "heartbeat"));
    expect(s.events).toHaveLength(0);
    expect(s.lastSeq).toBe(3);
  });

  it("tracks interventions through escalation and control transitions", () => {
    const raised = apply(
      initialRunStreamState,
      ev(1, "escalation_raised", {
        data: { intervention: interventionFixture },
        run_status: "waiting_intervention",
      }),
    );
    expect(raised.pendingIntervention?.state).toBe("paused");
    const taken = apply(
      raised,
      ev(2, "control_transition", {
        data: { intervention: { ...interventionFixture, state: "human" } },
      }),
    );
    expect(taken.pendingIntervention?.state).toBe("human");
    const back = apply(
      taken,
      ev(3, "control_transition", {
        data: { intervention: { ...interventionFixture, state: "resumed" } },
      }),
    );
    expect(back.pendingIntervention).toBeNull();
  });

  it("tracks clarifications and bumps screenshot version", () => {
    const asked = apply(
      initialRunStreamState,
      ev(1, "clarify", { data: { clarification: clarificationFixture } }),
    );
    expect(asked.pendingClarification?.question).toBe(clarificationFixture.question);
    const answered = apply(
      asked,
      ev(2, "clarification_answered"),
      ev(3, "screenshot_saved", { screenshot: "shots/0001.png" }),
    );
    expect(answered.pendingClarification).toBeNull();
    expect(answered.screenshotVersion).toBe(1);
  });

  it("seed does not override a live status", () => {
    const live = apply(
      initialRunStreamState,
      ev(1, "run_status", { run_status: "waiting_approval" }),
    );
    const seeded = runStreamReducer(live, { type: "seed", status: "running", lastSeq: 0 });
    expect(seeded.status).toBe("waiting_approval");
    expect(seeded.lastSeq).toBe(1);
  });
});
