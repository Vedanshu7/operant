import { useState, type ReactElement } from "react";

import { useDecideApproval } from "@/api/queries";
import type { Approval, RememberScope } from "@/api/types";
import { formatTime } from "@/lib/format";
import { approvalKindClasses, approvalKindLabel } from "@/lib/status";

import { Badge } from "./Badge";
import { Button } from "./Button";
import { Card } from "./Card";
import { ErrorBox } from "./ErrorBox";
import { KeyValueTable } from "./KeyValueTable";

export interface ApprovalCardProps {
  approval: Approval;
  onDecided?: (approval: Approval) => void;
}

const KIND_HELP: Record<Approval["kind"], string> = {
  scope: "The agent wants to go beyond the allowed apps or URLs.",
  mutating: "This action changes data in the target application.",
  sensitive_fill: "A sensitive value will be typed into the application.",
  sensitive_export: "Sensitive data would leave the application (copy, download, output).",
};

export function ApprovalCard({ approval, onDecided }: ApprovalCardProps): ReactElement {
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const decide = useDecideApproval();
  const noteRequiredForDeny = approval.kind === "sensitive_export";

  const submit = (approved: boolean, remember: RememberScope): void => {
    if (!approved && noteRequiredForDeny && note.trim() === "") {
      setNoteError("A note is required when denying a sensitive export.");
      return;
    }
    setNoteError(null);
    const trimmed = note.trim();
    decide.mutate(
      { id: approval.id, approved, remember, ...(trimmed ? { note: trimmed } : {}) },
      { onSuccess: (a) => onDecided?.(a) },
    );
  };

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          Approval needed
          <Badge className={approvalKindClasses(approval.kind)} title={KIND_HELP[approval.kind]}>
            {approvalKindLabel(approval.kind)}
          </Badge>
        </span>
      }
      className="border-amber-300 dark:border-amber-700"
    >
      <div className="space-y-3">
        <p className="text-sm font-medium">{approval.summary}</p>
        <p className="text-xs text-muted-foreground">{KIND_HELP[approval.kind]}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">action</dt>
          <dd className="font-mono">{approval.action_kind}</dd>
          {approval.app && (
            <>
              <dt className="text-muted-foreground">app</dt>
              <dd>{approval.app}</dd>
            </>
          )}
          {approval.step && (
            <>
              <dt className="text-muted-foreground">step</dt>
              <dd className="font-mono">{approval.step}</dd>
            </>
          )}
          <dt className="text-muted-foreground">raised</dt>
          <dd>{formatTime(approval.raised_at)}</dd>
        </dl>
        {Object.keys(approval.details).length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Details</h3>
            <KeyValueTable rows={approval.details} />
          </div>
        )}
        {approval.kind === "scope" && approval.proposed_grants.length > 0 && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
              Proposed grants
            </h3>
            <ul className="space-y-1 text-xs">
              {approval.proposed_grants.map((g) => (
                <li key={`${g.kind}:${g.pattern}`} className="flex items-center gap-2">
                  <Badge>{g.kind}</Badge>
                  <code className="font-mono">{g.pattern}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <label className="label" htmlFor={`note-${approval.id}`}>
            Note {noteRequiredForDeny ? "(required to deny)" : "(optional)"}
          </label>
          <textarea
            id={`note-${approval.id}`}
            className="input"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {noteError && (
            <p role="alert" className="mt-1 text-xs text-red-600">
              {noteError}
            </p>
          )}
        </div>
        <ErrorBox error={decide.error} />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            disabled={decide.isPending}
            onClick={() => submit(true, "once")}
          >
            Approve once
          </Button>
          <Button disabled={decide.isPending} onClick={() => submit(true, "process")}>
            Approve for this run
          </Button>
          <Button
            variant="danger"
            disabled={decide.isPending}
            onClick={() => submit(false, "once")}
          >
            Deny
          </Button>
        </div>
      </div>
    </Card>
  );
}
