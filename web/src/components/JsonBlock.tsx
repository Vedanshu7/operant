import type { ReactElement } from "react";

export interface JsonBlockProps {
  value: unknown;
  className?: string;
}

export function JsonBlock({ value, className = "" }: JsonBlockProps): ReactElement {
  return (
    <pre
      className={`overflow-x-auto rounded-md bg-zinc-100 p-2 font-mono text-xs leading-snug text-zinc-800 dark:bg-muted dark:text-zinc-200 ${className}`}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
