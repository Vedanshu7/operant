export interface InputRow {
  key: string;
  value: string;
}

export function rowsToRecord(rows: InputRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const k = r.key.trim();
    if (k) out[k] = r.value;
  }
  return out;
}
