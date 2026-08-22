import type { ReactElement } from "react";

import { useParams } from "react-router";

import { useRun } from "@/api/queries";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Card } from "@/components/Card";
import { ClarificationCard } from "@/components/ClarificationCard";
import { CredentialCard } from "@/components/CredentialCard";
import { ErrorBox } from "@/components/ErrorBox";
import { EventTimeline } from "@/components/EventTimeline";
import { InterventionCard } from "@/components/InterventionCard";
import { LiveScreenshot } from "@/components/LiveScreenshot";
import { Loading } from "@/components/Loading";
import { ResultPanel } from "@/components/ResultPanel";
import { RunHeader } from "@/components/RunHeader";
import { useRunStream } from "@/hooks/useRunStream";
import { isTerminal } from "@/lib/status";

export function RunPage(): ReactElement {
  const { id = "" } = useParams();
  const run = useRun(id);
  const stream = useRunStream(id, run.data?.status ?? null);

  if (run.isPending) return <Loading label="Loading run…" />;
  if (run.error || !run.data) return <ErrorBox error={run.error ?? "Run not found"} />;

  const detail = run.data;
  const status = stream.status ?? detail.status;
  const running = !isTerminal(status);
  const approval =
    stream.pendingApproval ?? (status === "waiting_approval" ? detail.pending_approval : null);
  const intervention =
    stream.pendingIntervention ??
    (status === "waiting_intervention" ? detail.pending_intervention : null);
  const clarification =
    stream.pendingClarification ??
    (status === "waiting_clarification" ? detail.pending_clarification : null);
  const credential = stream.pendingCredential;

  return (
    <div className="space-y-4">
      <RunHeader run={detail} liveStatus={stream.status} connected={stream.connected} />
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card title="Timeline">
          <EventTimeline events={stream.events} live={running} />
        </Card>
        <div className="space-y-4">
          <LiveScreenshot runId={id} version={stream.screenshotVersion} running={running} />
          {approval && <ApprovalCard approval={approval} />}
          {intervention && <InterventionCard intervention={intervention} runId={id} />}
          {clarification && <ClarificationCard clarification={clarification} />}
          {credential && <CredentialCard credential={credential} />}
          <ResultPanel run={{ ...detail, status }} />
          {Object.keys(detail.inputs).length > 0 && (
            <Card title="Inputs">
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                {Object.entries(detail.inputs).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-muted-foreground">{k}</dt>
                    <dd className="break-all font-mono">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
