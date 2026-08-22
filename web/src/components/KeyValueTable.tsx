import type { ReactElement } from "react";

export interface KeyValueTableProps {
  rows: Record<string, string>;
  emptyLabel?: string;
}

export function KeyValueTable({ rows, emptyLabel = "None" }: KeyValueTableProps): ReactElement {
  const entries = Object.entries(rows);
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  return (
    <table className="table">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td className="w-40 font-mono text-xs text-muted-foreground">{k}</td>
            <td className="break-all font-mono text-xs">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
