import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useEffect, useReducer, useRef, useState } from "react";

import { authHeaders, buildUrl } from "@/api/client";
import type { RunStatus, SseEnvelope } from "@/api/types";
import { redirectToLogin } from "@/lib/auth";
import { isTerminal } from "@/lib/status";

import { initialRunStreamState, runStreamReducer, type RunStreamState } from "./runStreamReducer";

const RECONNECT_DELAY_MS = 2000;

class FatalStreamError extends Error {}

export function useRunStream(runId: string, initialStatus: RunStatus | null): RunStreamState {
  const [state, dispatch] = useReducer(runStreamReducer, initialRunStreamState);
  const [attempt, setAttempt] = useState(0);
  const lastSeqRef = useRef(0);
  lastSeqRef.current = state.lastSeq;

  useEffect(() => {
    dispatch({ type: "reset" });
    setAttempt(0);
  }, [runId]);

  useEffect(() => {
    if (initialStatus) dispatch({ type: "seed", status: initialStatus });
  }, [initialStatus]);

  const effectiveStatus = state.status ?? initialStatus;
  // Stream once the status is known, terminal runs included: the endpoint
  // replays the full history then closes, so a finished run still shows its
  // timeline. Only live runs keep reconnecting.
  const shouldStream = effectiveStatus !== null;
  const terminal = effectiveStatus !== null && isTerminal(effectiveStatus);

  useEffect(() => {
    if (!shouldStream) return;
    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const scheduleReconnect = (): void => {
      if (terminal || controller.signal.aborted || reconnectTimer !== undefined) return;
      reconnectTimer = setTimeout(() => setAttempt((a) => a + 1), RECONNECT_DELAY_MS);
    };

    const after = lastSeqRef.current > 0 ? lastSeqRef.current : undefined;
    void fetchEventSource(buildUrl(`/runs/${runId}/events`, { after }), {
      headers: { ...authHeaders(), Accept: "text/event-stream" },
      signal: controller.signal,
      openWhenHidden: true,
      onopen: (res) => {
        if (res.status === 401) {
          redirectToLogin();
          throw new FatalStreamError("unauthorized");
        }
        if (!res.ok) throw new Error(`stream failed: ${res.status}`);
        dispatch({ type: "connected", connected: true });
        return Promise.resolve();
      },
      onmessage: (msg) => {
        if (!msg.data) return;
        let env: SseEnvelope;
        try {
          env = JSON.parse(msg.data) as SseEnvelope;
        } catch {
          return;
        }
        if (msg.id) {
          const seq = Number(msg.id);
          if (Number.isFinite(seq)) env = { ...env, seq };
        }
        dispatch({ type: "event", event: env });
        if (isTerminal(env.run_status)) controller.abort();
      },
      onclose: () => {
        dispatch({ type: "connected", connected: false });
        scheduleReconnect();
        throw new FatalStreamError("closed");
      },
      onerror: (err: unknown) => {
        dispatch({ type: "connected", connected: false });
        if (!(err instanceof FatalStreamError)) scheduleReconnect();
        throw err instanceof Error ? err : new Error(String(err));
      },
    }).catch(() => {
      dispatch({ type: "connected", connected: false });
    });

    return () => {
      controller.abort();
      if (reconnectTimer !== undefined) clearTimeout(reconnectTimer);
    };
  }, [runId, shouldStream, terminal, attempt]);

  return state;
}
