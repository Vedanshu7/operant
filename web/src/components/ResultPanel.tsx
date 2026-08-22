import type { ReactElement } from "react";

import { Link } from "react-router";

import type { DiscoveryOutcome, ReplayResult, RunDetail } from "@/api/types";

import { Badge } from "./Badge";
import { Card } from "./Card";
import { KeyValueTable } from "./KeyValueTable";

export interface ResultPanelProps {
  run: RunDetail;
}

function isDiscoveryOutcome(r: ReplayResult | DiscoveryOutcome): r is DiscoveryOutcome {
  return "graph_version" in r;
}

function ReplayResultView({
  result,
  runId,
}: {
  result: ReplayResult;
  runId: string;
}): ReactElement {
  switch (result.status) {
    case "success":
      return (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Outputs</h3>
          <KeyValueTable rows={result.outputs} emptyLabel="No outputs" />
        </div>
      );
    case "business_outcome":
      return (
        <div className="space-y-1 text-sm">
          <p>
            <Badge className="bg-teal-100 text-teal-900 dark:bg-teal-900 dark:text-teal-100">
              {result.outcome}
            </Badge>
          </p>
          <p>{result.detail}</p>
        </div>
      );
    case "escalated":
      return (
        <div className="space-y-1 text-sm">
          <p>
            Escalated to a human - intervention{" "}
            <code className="font-mono text-xs">{result.intervention_id}</code>
          </p>
          <p>Resolution: {result.resolution}</p>
        </div>
      );
    case "failure":
      return (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">class</dt>
          <dd>
            <Badge className="bg-red-100 text-red-900 dark:bg-red-900 dark:text-red-100">
              {result.failure.failure_class}
            </Badge>
          </dd>
          <dt className="text-muted-foreground">at edge</dt>
          <dd className="font-mono text-xs">{result.failure.at_edge}</dd>
          <dt className="text-muted-foreground">expected</dt>
          <dd>{result.failure.expected}</dd>
          <dt className="text-muted-foreground">observed</dt>
          <dd>{result.failure.observed}</dd>
          {result.failure.evidence_refs.length > 0 && (
            <>
              <dt className="text-muted-foreground">evidence</dt>
              <dd className="space-x-2">
                {result.failure.evidence_refs.map((ref) => (
                  <Link
                    key={ref}
                    to={`/evidence/${runId}?file=${encodeURIComponent(ref)}`}
                    className="font-mono text-xs text-primary hover:underline"
                  >
                    {ref}
                  </Link>
                ))}
              </dd>
            </>
          )}
        </dl>
      );
  }
}

export function ResultPanel({ run }: ResultPanelProps): ReactElement | null {
  if (!run.result && !run.error) return null;
  return (
    <Card title="Result">
      {run.error && (
        <p className="mb-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
          {run.error}
        </p>
      )}
      {run.result &&
        (isDiscoveryOutcome(run.result) ? (
          <div className="space-y-2 text-sm">
            <p>
              Compiled capability{" "}
              <Link
                to={`/capabilities/${run.result.capability_id}`}
                className="font-mono text-primary hover:underline"
              >
                {run.result.capability_id}
              </Link>{" "}
              (graph v{run.result.graph_version})
            </p>
            <p className="text-xs text-muted-foreground">
              inputs: {run.result.inputs.join(", ") || "none"} · outputs:{" "}
              {run.result.outputs.join(", ") || "none"}
            </p>
          </div>
        ) : (
          <ReplayResultView result={run.result} runId={run.id} />
        ))}
    </Card>
  );
}
