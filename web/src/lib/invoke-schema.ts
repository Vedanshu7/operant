import { z } from "zod";

import type { IoField } from "@/api/types";

export type InvokeValues = Record<string, string | boolean>;

export function buildInvokeSchema(fields: Record<string, IoField>): z.ZodType<InvokeValues> {
  const shape: Record<string, z.ZodType> = {};
  for (const [name, field] of Object.entries(fields)) {
    switch (field.type) {
      case "boolean":
        shape[name] = z.boolean();
        break;
      case "number": {
        const num = z
          .string()
          .trim()
          .refine((v) => v === "" || !Number.isNaN(Number(v)), { message: "Must be a number" });
        shape[name] = field.required ? num.refine((v) => v !== "", { message: "Required" }) : num;
        break;
      }
      case "string": {
        const str = z.string();
        shape[name] = field.required ? str.min(1, { message: "Required" }) : str;
        break;
      }
    }
  }
  return z.object(shape) as unknown as z.ZodType<InvokeValues>;
}

export function defaultInvokeValues(fields: Record<string, IoField>): InvokeValues {
  const out: InvokeValues = {};
  for (const [name, field] of Object.entries(fields))
    out[name] = field.type === "boolean" ? false : "";
  return out;
}

export function invokeValuesToStrings(values: InvokeValues): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    if (typeof v === "boolean") out[k] = v ? "true" : "false";
    else if (v !== "") out[k] = v;
  }
  return out;
}
