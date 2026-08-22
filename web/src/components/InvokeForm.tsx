import { useId, useState, type FormEvent, type ReactElement } from "react";

import type { IoField } from "@/api/types";
import {
  buildInvokeSchema,
  defaultInvokeValues,
  invokeValuesToStrings,
  type InvokeValues,
} from "@/lib/invoke-schema";

import { Badge } from "./Badge";
import { Button } from "./Button";
import { Field } from "./Field";

export interface InvokeFormProps {
  fields: Record<string, IoField>;
  onSubmit: (inputs: Record<string, string>) => void;
  submitLabel?: string;
  busy?: boolean;
  formId?: string;
  hideSubmit?: boolean;
}

export function InvokeForm({
  fields,
  onSubmit,
  submitLabel = "Invoke",
  busy = false,
  formId,
  hideSubmit = false,
}: InvokeFormProps): ReactElement {
  const [values, setValues] = useState<InvokeValues>(() => defaultInvokeValues(fields));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const idPrefix = useId();
  const names = Object.keys(fields);

  const handleSubmit = (e: FormEvent): void => {
    e.preventDefault();
    const result = buildInvokeSchema(fields).safeParse(values);
    if (!result.success) {
      const next: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const key = issue.path[0];
        if (typeof key === "string" && !next[key]) next[key] = issue.message;
      }
      setErrors(next);
      return;
    }
    setErrors({});
    onSubmit(invokeValuesToStrings(result.data));
  };

  return (
    <form id={formId} onSubmit={handleSubmit} className="space-y-3" noValidate>
      {names.length === 0 && (
        <p className="text-sm text-muted-foreground">This capability takes no inputs.</p>
      )}
      {names.map((name) => {
        const field = fields[name];
        if (!field) return null;
        const id = `${idPrefix}-${name}`;
        const label = (
          <span className="inline-flex items-center gap-1.5">
            <span className="font-mono">{name}</span>
            {field.required && <span className="text-red-500">*</span>}
            {field.sensitive && (
              <Badge className="bg-fuchsia-100 text-fuchsia-900 dark:bg-fuchsia-900 dark:text-fuchsia-100">
                sensitive
              </Badge>
            )}
            {field.data_class !== "none" && <Badge>{field.data_class}</Badge>}
          </span>
        );
        if (field.type === "boolean") {
          return (
            <div key={name} className="flex items-start gap-2">
              <input
                id={id}
                type="checkbox"
                className="mt-1"
                checked={values[name] === true}
                onChange={(e) => setValues({ ...values, [name]: e.target.checked })}
              />
              <label htmlFor={id} className="text-sm">
                {label}
                <span className="block text-xs text-muted-foreground">{field.description}</span>
              </label>
            </div>
          );
        }
        const value = values[name];
        return (
          <Field
            key={name}
            label={label}
            htmlFor={id}
            hint={field.description}
            error={errors[name]}
          >
            <input
              id={id}
              className="input"
              type={field.sensitive ? "password" : field.type === "number" ? "number" : "text"}
              autoComplete={field.sensitive ? "off" : undefined}
              step={field.type === "number" ? "any" : undefined}
              value={typeof value === "string" ? value : ""}
              aria-invalid={errors[name] ? true : undefined}
              onChange={(e) => setValues({ ...values, [name]: e.target.value })}
            />
          </Field>
        );
      })}
      {!hideSubmit && (
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Submitting…" : submitLabel}
        </Button>
      )}
    </form>
  );
}
