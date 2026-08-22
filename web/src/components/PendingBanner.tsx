import type { ReactElement } from "react";

import { ArrowRight, BellRing } from "lucide-react";
import { Link } from "react-router";

import { usePendingApprovals } from "@/api/queries";
import { approvalKindClasses, approvalKindLabel } from "@/lib/status";

import { Badge } from "./Badge";

export function PendingBanner(): ReactElement | null {
  const pending = usePendingApprovals();
  const items = pending.data ?? [];
  if (items.length === 0) return null;
  return (
    <div
      role="status"
      className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm"
    >
      <p className="mb-2 flex items-center gap-2 font-semibold">
        <BellRing className="size-4 text-warning" />
        Pending human input ({items.length})
      </p>
      <ul className="space-y-1.5">
        {items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-2">
            <Badge className={approvalKindClasses(a.kind)}>{approvalKindLabel(a.kind)}</Badge>
            <span className="flex-1 truncate text-foreground">{a.summary}</span>
            <Link
              to={`/runs/${a.run_id}`}
              className="flex items-center gap-1 font-medium text-primary hover:underline"
            >
              Open run
              <ArrowRight className="size-3.5" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
