import type { ReactElement } from "react";

import { CircleAlert } from "lucide-react";

import { errorMessage } from "@/lib/errors";
import { cn } from "@/lib/utils";

export interface ErrorBoxProps {
  error: unknown;
  className?: string;
}

export function ErrorBox({ error, className = "" }: ErrorBoxProps): ReactElement | null {
  if (!error) return null;
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive",
        className,
      )}
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0" />
      <span>{errorMessage(error)}</span>
    </div>
  );
}
