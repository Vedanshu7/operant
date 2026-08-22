import { useState, type ReactElement } from "react";

import { useInterventionAction } from "@/api/queries";
import type { Intervention } from "@/api/types";
import { useAuthedBlobUrl } from "@/hooks/useAuthedBlobUrl";
import { formatTime } from "@/lib/format";

import { Badge } from "./Badge";
import { Button } from "./Button";
import { Card } from "./Card";
import { ErrorBox } from "./ErrorBox";

export interface InterventionCardProps {
  intervention: Intervention;
  runId: string;
}

export function InterventionCard({ intervention, runId }: InterventionCardProps): ReactElement {
  const [note, setNote] = useState("");
  const act = useInterventionAction();
  const shot = useAuthedBlobUrl(
    intervention.screenshot_file
      ? `/evidence/${runId}/files/${intervention.screenshot_file}`
      : null,
  );
  const isHuman = intervention.state === "human";
  const run = (action: "take" | "handback" | "abandon"): void => {
    const trimmed = note.trim();
    act.mutate({ id: intervention.id, action, ...(trimmed ? { note: trimmed } : {}) });
  };

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          Intervention
          <Badge className="bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100">
            {intervention.state}
          </Badge>
        </span>
      }
      className="border-orange-300 dark:border-orange-700"
    >
      <div className="space-y-3">
        <p className="text-sm font-medium">{intervention.reason}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {intervention.page_title && (
            <>
              <dt className="text-muted-foreground">page</dt>
              <dd>{intervention.page_title}</dd>
            </>
          )}
          {intervention.edge_id && (
            <>
              <dt className="text-muted-foreground">edge</dt>
              <dd className="font-mono">{intervention.edge_id}</dd>
            </>
          )}
          <dt className="text-muted-foreground">raised</dt>
          <dd>{formatTime(intervention.raised_at)}</dd>
          {intervention.taken_at && (
            <>
              <dt className="text-muted-foreground">taken</dt>
              <dd>{formatTime(intervention.taken_at)}</dd>
            </>
          )}
        </dl>
        {shot.url && (
          <img
            src={shot.url}
            alt="Screenshot at escalation"
            className="w-full rounded border border-border"
          />
        )}
        {isHuman && (
          <p className="rounded-md bg-orange-50 px-3 py-2 text-xs text-orange-900 dark:bg-orange-950 dark:text-orange-100">
            You have control of the live session. Fix the situation in the app, then hand control
            back.
          </p>
        )}
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Human actions
          </h3>
          {intervention.human_actions.length === 0 ? (
            <p className="text-xs text-muted-foreground">None recorded yet.</p>
          ) : (
            <ol className="list-decimal space-y-0.5 pl-5 font-mono text-xs">
              {intervention.human_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ol>
          )}
        </div>
        <div>
          <label className="label" htmlFor={`iv-note-${intervention.id}`}>
            Note (optional)
          </label>
          <textarea
            id={`iv-note-${intervention.id}`}
            className="input"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <ErrorBox error={act.error} />
        <div className="flex flex-wrap gap-2">
          {!isHuman ? (
            <Button variant="primary" disabled={act.isPending} onClick={() => run("take")}>
              Take control
            </Button>
          ) : (
            <>
              <Button variant="primary" disabled={act.isPending} onClick={() => run("handback")}>
                Hand control back
              </Button>
              <Button variant="danger" disabled={act.isPending} onClick={() => run("abandon")}>
                Mark unrecoverable
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
