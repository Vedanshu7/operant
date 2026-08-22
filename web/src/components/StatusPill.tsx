import type { ReactElement } from "react";

import type { RunStatus } from "@/api/types";
import { statusClasses, statusLabel } from "@/lib/status";

import { Badge } from "./Badge";

export interface StatusPillProps {
  status: RunStatus;
}

export function StatusPill({ status }: StatusPillProps): ReactElement {
  return (
    <Badge className={statusClasses(status)} title={status}>
      <span data-testid="status-pill">{statusLabel(status)}</span>
    </Badge>
  );
}
