import type { ReactElement } from "react";

export interface PresenceDotProps {
  present: boolean | null;
  label?: string;
}

export function PresenceDot({ present, label }: PresenceDotProps): ReactElement {
  const colour = present === null ? "bg-zinc-400" : present ? "bg-emerald-500" : "bg-red-500";
  const text = present === null ? "unknown" : present ? "present" : "missing";
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs"
      title={`${label ?? "secret"}: ${text}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${colour}`} aria-label={text} />
      {label && <span className="font-mono">{label}</span>}
    </span>
  );
}
