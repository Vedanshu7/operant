import type { ReactNode, ReactElement } from "react";

import { cn } from "@/lib/utils";

export interface BadgeProps {
  children: ReactNode;
  className?: string;
  title?: string;
}

export function Badge({ children, className = "", title }: BadgeProps): ReactElement {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium capitalize",
        className || "border-transparent bg-secondary text-secondary-foreground",
      )}
    >
      {children}
    </span>
  );
}
