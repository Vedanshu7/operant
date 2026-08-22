import type {
  Approval,
  Clarification,
  CredentialRequest,
  Intervention,
  RunStatus,
  SseEnvelope,
} from "@/api/types";

export interface RunStreamState {
  events: SseEnvelope[];
  status: RunStatus | null;
  pendingApproval: Approval | null;
  pendingIntervention: Intervention | null;
  pendingClarification: Clarification | null;
  pendingCredential: CredentialRequest | null;
  lastSeq: number;
  screenshotVersion: number;
  connected: boolean;
}

export type RunStreamAction =
  | { type: "event"; event: SseEnvelope }
  | { type: "connected"; connected: boolean }
  | { type: "seed"; status: RunStatus; lastSeq?: number }
  | { type: "reset" };

export const initialRunStreamState: RunStreamState = {
  events: [],
  status: null,
  pendingApproval: null,
  pendingIntervention: null,
  pendingClarification: null,
  pendingCredential: null,
  lastSeq: 0,
  screenshotVersion: 0,
  connected: false,
};

export const MAX_EVENTS = 2000;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function asText(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function pick(data: Record<string, unknown>, ...keys: string[]): Record<string, unknown> | null {
  for (const k of keys) {
    const v = data[k];
    if (isRecord(v)) return v;
  }
  return null;
}

function applyEvent(state: RunStreamState, ev: SseEnvelope): RunStreamState {
  let next: RunStreamState = {
    ...state,
    lastSeq: Math.max(state.lastSeq, ev.seq),
    status: ev.run_status,
  };
  if (ev.type === "heartbeat") return next;

  const events =
    state.events.length >= MAX_EVENTS ? state.events.slice(-MAX_EVENTS + 1) : state.events;
  next = { ...next, events: [...events, ev] };
  if (ev.screenshot) next.screenshotVersion = state.screenshotVersion + 1;

  switch (ev.type) {
    case "approval_requested":
      next.pendingApproval = pick(ev.data, "approval") as Approval | null;
      break;
    case "approval_resolved":
      next.pendingApproval = null;
      break;
    case "escalation_raised":
      next.pendingIntervention = pick(ev.data, "intervention", "escalation") as Intervention | null;
      break;
    case "control_transition": {
      const iv = pick(ev.data, "intervention", "escalation") as Intervention | null;
      if (iv) {
        next.pendingIntervention = iv.state === "paused" || iv.state === "human" ? iv : null;
      } else if (ev.data.state === "resumed" || ev.data.state === "abandoned") {
        next.pendingIntervention = null;
      } else if (next.pendingIntervention && typeof ev.data.state === "string") {
        next.pendingIntervention = {
          ...next.pendingIntervention,
          state: ev.data.state as Intervention["state"],
        };
      }
      break;
    }
    case "clarify":
      next.pendingClarification = pick(ev.data, "clarification") as Clarification | null;
      break;
    case "clarification_answered":
      next.pendingClarification = null;
      break;
    case "credential_requested":
      next.pendingCredential = {
        request_id: asText(ev.data.request_id),
        name: asText(ev.data.name),
        reason: asText(ev.data.reason),
      };
      break;
    case "credential_provided":
      next.pendingCredential = null;
      break;
    case "screenshot_saved":
      next.screenshotVersion = state.screenshotVersion + 1;
      break;
    case "replay_finished":
    case "goal_complete":
      next.pendingApproval = null;
      next.pendingIntervention = null;
      next.pendingClarification = null;
      next.pendingCredential = null;
      break;
    default:
      break;
  }
  return next;
}

export function runStreamReducer(state: RunStreamState, action: RunStreamAction): RunStreamState {
  switch (action.type) {
    case "event":
      return applyEvent(state, action.event);
    case "connected":
      return state.connected === action.connected
        ? state
        : { ...state, connected: action.connected };
    case "seed":
      return {
        ...state,
        status: state.status ?? action.status,
        lastSeq: Math.max(state.lastSeq, action.lastSeq ?? 0),
      };
    case "reset":
      return initialRunStreamState;
  }
}
