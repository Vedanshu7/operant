import type { ReactElement } from "react";

import type { InputRow } from "@/lib/inputs";

import { Button } from "./Button";

export interface InputsEditorProps {
  rows: InputRow[];
  onChange: (rows: InputRow[]) => void;
}

export function InputsEditor({ rows, onChange }: InputsEditorProps): ReactElement {
  const update = (i: number, patch: Partial<InputRow>): void =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex gap-2">
          <input
            aria-label={`Input ${i + 1} key`}
            className="input font-mono"
            placeholder="key"
            value={row.key}
            onChange={(e) => update(i, { key: e.target.value })}
          />
          <input
            aria-label={`Input ${i + 1} value`}
            className="input"
            placeholder="value"
            value={row.value}
            onChange={(e) => update(i, { value: e.target.value })}
          />
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Remove input ${i + 1}`}
            onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
          >
            ×
          </Button>
        </div>
      ))}
      <Button size="sm" onClick={() => onChange([...rows, { key: "", value: "" }])}>
        + Add input
      </Button>
    </div>
  );
}
