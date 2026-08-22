import type { ReactElement } from "react";

import { Link } from "react-router";

import type { RunSummary } from "@/api/types";
import { formatDuration, formatTime, shortId } from "@/lib/format";

import { Badge } from "./Badge";
import { StatusPill } from "./StatusPill";

export interface RunsTableProps {
  runs: RunSummary[];
}

export function RunsTable({ runs }: RunsTableProps): ReactElement {
  if (runs.length === 0)
    return <p className="py-6 text-center text-sm text-muted-foreground">No runs match.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Id</th>
            <th>Kind</th>
            <th>Status</th>
            <th>Goal / capability</th>
            <th>Created</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="hover:bg-accent/40">
              <td>
                <Link
                  to={`/runs/${r.id}`}
                  className="font-mono text-xs text-primary hover:underline"
                  title={r.id}
                >
                  {shortId(r.id)}
                </Link>
              </td>
              <td>
                <Badge>{r.kind}</Badge>
              </td>
              <td>
                <StatusPill status={r.status} />
              </td>
              <td className="max-w-md truncate">
                {r.kind === "discovery" ? (
                  <span title={r.goal ?? ""}>{r.goal ?? "-"}</span>
                ) : (
                  <span className="font-mono text-xs">{r.capability_id ?? "-"}</span>
                )}
                {r.tenant && (
                  <span className="ml-2 text-xs text-muted-foreground">@{r.tenant}</span>
                )}
              </td>
              <td className="whitespace-nowrap text-xs text-muted-foreground">
                {formatTime(r.created_at)}
              </td>
              <td className="whitespace-nowrap text-xs">
                {formatDuration(r.started_at, r.finished_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
