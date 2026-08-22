import { useState, type FormEvent, type ReactElement } from "react";

import type { SecretRef, TenantBinding } from "@/api/types";
import { rowsToRecord, type InputRow } from "@/lib/inputs";

import { Button } from "./Button";
import { Field } from "./Field";
import { InputsEditor } from "./InputsEditor";

export interface TenantEditorProps {
  name: string;
  binding: TenantBinding;
  secretRefs: SecretRef[];
  onSave: (name: string, binding: TenantBinding) => void;
  onCancel: () => void;
  busy?: boolean;
}

export function TenantEditor({
  name,
  binding,
  secretRefs,
  onSave,
  onCancel,
  busy = false,
}: TenantEditorProps): ReactElement {
  const [baseUrl, setBaseUrl] = useState(binding.base_url);
  const [entryPath, setEntryPath] = useState(binding.entry_path);
  const [rows, setRows] = useState<InputRow[]>(
    Object.entries(binding.secret_refs).map(([key, value]) => ({ key, value })),
  );
  const known = new Set(secretRefs.map((s) => s.name));
  const unknown = rows.map((r) => r.value).filter((v) => v && !known.has(v));

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    onSave(name, { base_url: baseUrl, entry_path: entryPath, secret_refs: rowsToRecord(rows) });
  };

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border border-blue-300 p-3 dark:border-blue-800"
    >
      <h3 className="text-sm font-semibold">
        Edit tenant <span className="font-mono">{name}</span>
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Base URL" htmlFor={`base-${name}`}>
          <input
            id={`base-${name}`}
            className="input font-mono"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </Field>
        <Field label="Entry path" htmlFor={`entry-${name}`}>
          <input
            id={`entry-${name}`}
            className="input font-mono"
            value={entryPath}
            onChange={(e) => setEntryPath(e.target.value)}
          />
        </Field>
      </div>
      <Field
        label="Secret refs (field → ref name)"
        hint="Only reference names are stored here; values live in the secret backend."
        error={unknown.length > 0 ? `Unknown secret refs: ${unknown.join(", ")}` : undefined}
      >
        <InputsEditor rows={rows} onChange={setRows} />
      </Field>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          Save tenant
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
