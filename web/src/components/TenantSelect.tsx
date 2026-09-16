import type { ReactElement } from "react";

export interface TenantSelectProps {
  id: string;
  tenants: readonly string[];
  value: string;
  onChange: (tenant: string) => void;
  defaultLabel: string;
}

export function TenantSelect({
  id,
  tenants,
  value,
  onChange,
  defaultLabel,
}: TenantSelectProps): ReactElement {
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{defaultLabel}</option>
      {tenants.map((t) => (
        <option key={t} value={t}>
          {t}
        </option>
      ))}
    </select>
  );
}
