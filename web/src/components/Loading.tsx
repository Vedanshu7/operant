import type { ReactElement } from "react";

import { Loader2 } from "lucide-react";

export interface LoadingProps {
  label?: string;
}

export function Loading({ label = "Loading…" }: LoadingProps): ReactElement {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground" role="status">
      <Loader2 className="size-4 animate-spin" />
      {label}
    </div>
  );
}
