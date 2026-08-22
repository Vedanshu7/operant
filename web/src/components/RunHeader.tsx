import type { ReactElement } from "react";

import { Link } from "react-router";

import { useCancelRun } from "@/api/queries";
import type { RunDetail, RunStatus } from "@/api/types";
import { formatDuration, formatTime } from "@/lib/format";
import { isTerminal } from "@/lib/status";

import { Badge } from "./Badge";
import { Button } from "./Button";
import { ErrorBox } from "./ErrorBox";
import { StatusPill } from "./StatusPill";

export interface RunHeaderProps {
  run: RunDetail;
  liveStatus: RunStatus | null;
  connected: boolean;
}

export function RunHeader({ run, liveStatus, connected }: RunHeaderProps): ReactElement {
  const status = liveStatus ?? run.status;
  const cancel = useCancelRun(run.id);
  const title =
    run.kind === "discovery" ? (run.goal ?? "Discovery") : (run.capability_id ?? "Replay");

  return (
    <header className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={status} />
        <Badge>{run.kind}</Badge>
        {status === "waiting_driver" && run.lease_position !== null && (
          <Badge className="bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
            lease queue position {run.lease_position}
          </Badge>
        )}
        {!isTerminal(status) && (
          <span
            className={`text-xs ${connected ? "text-success" : "text-muted-foreground"}`}
            title={connected ? "Event stream connected" : "Event stream disconnected"}
          >
            ● {connected ? "live" : "reconnecting"}
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          {run.evidence_dir && (
            <Link to={`/evidence/${run.id}`} className="text-sm text-primary hover:underline">
              Evidence
            </Link>
          )}
          {!isTerminal(status) && (
            <Button
              variant="danger"
              size="sm"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              Cancel
            </Button>
          )}
        </span>
      </div>
      <h1 className="text-lg font-semibold leading-tight">{title}</h1>
      <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <div>
          <dt className="inline">id </dt>
          <dd className="inline font-mono text-foreground">{run.id}</dd>
        </div>
        {run.capability_id && run.kind === "discovery" && (
          <div>
            <dt className="inline">capability </dt>
            <dd className="inline font-mono">
              <Link
                to={`/capabilities/${run.capability_id}`}
                className="text-primary hover:underline"
              >
                {run.capability_id}
              </Link>
            </dd>
          </div>
        )}
        {run.profile_id && (
          <div>
            <dt className="inline">profile </dt>
            <dd className="inline">
              <Link to={`/profiles/${run.profile_id}`} className="text-primary hover:underline">
                {run.profile_id}
              </Link>
            </dd>
          </div>
        )}
        {run.tenant && (
          <div>
            <dt className="inline">tenant </dt>
            <dd className="inline">{run.tenant}</dd>
          </div>
        )}
        <div>
          <dt className="inline">created </dt>
          <dd className="inline">{formatTime(run.created_at)}</dd>
        </div>
        <div>
          <dt className="inline">duration </dt>
          <dd className="inline">{formatDuration(run.started_at, run.finished_at)}</dd>
        </div>
      </dl>
      <ErrorBox error={cancel.error} />
    </header>
  );
}
