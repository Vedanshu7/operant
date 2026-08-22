import { useState, type ReactElement } from "react";

import { Plus } from "lucide-react";
import { Link } from "react-router";

import { useRuns } from "@/api/queries";
import type { RunKind, RunStatus } from "@/api/types";
import { Button } from "@/components/Button";
import { ErrorBox } from "@/components/ErrorBox";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";
import { PendingBanner } from "@/components/PendingBanner";
import { RunsTable } from "@/components/RunsTable";
import { RUN_STATUSES, statusLabel } from "@/lib/status";

export function RunsPage(): ReactElement {
  const [kind, setKind] = useState<RunKind | "">("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const runs = useRuns({
    ...(kind ? { kind } : {}),
    ...(status ? { status } : {}),
    ...(cursor ? { cursor } : {}),
    limit: 50,
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Runs"
        description="Every discovery and replay, with live status and pending human input."
        actions={
          <Link
            to="/"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow-xs transition-colors hover:bg-primary/90"
          >
            <Plus className="size-4" />
            New run
          </Link>
        }
      />
      <PendingBanner />
      <div className="rounded-xl border border-border bg-card shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <select
            aria-label="Kind"
            className="input h-8 w-auto"
            value={kind}
            onChange={(e) => setKind(e.target.value as RunKind | "")}
          >
            <option value="">All kinds</option>
            <option value="discovery">Discovery</option>
            <option value="replay">Replay</option>
          </select>
          <select
            aria-label="Status"
            className="input h-8 w-auto"
            value={status}
            onChange={(e) => setStatus(e.target.value as RunStatus | "")}
          >
            <option value="">All statuses</option>
            {RUN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <div className="p-1">
          {runs.isPending && <Loading />}
          <ErrorBox error={runs.error} className="m-3" />
          {runs.data && <RunsTable runs={runs.data.items} />}
        </div>
        {runs.data?.next_cursor && (
          <div className="border-t border-border p-3 text-right">
            <Button size="sm" onClick={() => setCursor(runs.data.next_cursor ?? undefined)}>
              Next page
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
