import { useState, type ReactElement } from "react";

import { ChevronRight } from "lucide-react";

import type { SseEnvelope } from "@/api/types";
import { formatClock } from "@/lib/format";
import { cn } from "@/lib/utils";

import { JsonBlock } from "./JsonBlock";

const DOT: Record<string, string> = {
  approval_requested: "bg-warning",
  approval_resolved: "bg-warning/60",
  escalation_raised: "bg-orange-500",
  control_transition: "bg-orange-400",
  clarify: "bg-violet-500",
  clarification_answered: "bg-violet-400",
  screenshot_saved: "bg-sky-500",
  run_status: "bg-muted-foreground",
  replay_finished: "bg-success",
  goal_complete: "bg-success",
  error: "bg-destructive",
};

export interface EventRowProps {
  event: SseEnvelope;
  last?: boolean;
}

export function EventRow({ event, last = false }: EventRowProps): ReactElement {
  const [open, setOpen] = useState(false);
  const hasData = Object.keys(event.data).length > 0;
  const dot = DOT[event.type] ?? "bg-primary";
  return (
    <li className="relative flex gap-3">
      <div className="flex flex-col items-center pt-1.5">
        <span className={cn("size-2.5 shrink-0 rounded-full ring-4 ring-card", dot)} />
        {!last && <span className="w-px flex-1 bg-border" />}
      </div>
      <div className="min-w-0 flex-1 pb-3">
        <button
          type="button"
          className="flex w-full items-center gap-2 text-left"
          onClick={() => hasData && setOpen((o) => !o)}
          aria-expanded={open}
        >
          <span className="font-medium text-foreground/90">{event.type.replace(/_/g, " ")}</span>
          <span className="font-mono text-[11px] text-muted-foreground">
            {formatClock(event.at)}
          </span>
          <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground">
            #{event.seq}
          </span>
          {hasData && (
            <ChevronRight
              className={cn(
                "size-3.5 shrink-0 text-muted-foreground transition-transform",
                open && "rotate-90",
              )}
            />
          )}
        </button>
        {event.summary && (
          <p className="mt-0.5 break-words text-sm text-muted-foreground">{event.summary}</p>
        )}
        {open && hasData && <JsonBlock value={event.data} className="mt-1.5" />}
      </div>
    </li>
  );
}
