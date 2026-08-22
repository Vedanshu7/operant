import { useState, type FormEvent, type ReactElement } from "react";

import type { AppProfile, SensitiveFillMode } from "@/api/types";

import { Button } from "./Button";
import { Field } from "./Field";
import { TagInput } from "./TagInput";

export interface ProfileFormProps {
  profile: AppProfile;
  onSave: (profile: AppProfile) => void;
  busy?: boolean;
}

export function ProfileForm({ profile, onSave, busy = false }: ProfileFormProps): ReactElement {
  const [draft, setDraft] = useState<AppProfile>(profile);
  const policy = draft.policy;
  const setPolicy = (patch: Partial<AppProfile["policy"]>): void =>
    setDraft({ ...draft, policy: { ...policy, ...patch } });
  const setApproval = (patch: Partial<AppProfile["policy"]["approval"]>): void =>
    setPolicy({ approval: { ...policy.approval, ...patch } });

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    onSave(draft);
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="App name" htmlFor="app_name">
          <input
            id="app_name"
            className="input"
            value={draft.app_name}
            onChange={(e) => setDraft({ ...draft, app_name: e.target.value })}
          />
        </Field>
        <Field label="Window title pattern" htmlFor="window_title_pattern">
          <input
            id="window_title_pattern"
            className="input font-mono"
            value={draft.window_title_pattern}
            onChange={(e) => setDraft({ ...draft, window_title_pattern: e.target.value })}
          />
        </Field>
        <Field label="Default tenant" htmlFor="default_tenant">
          <select
            id="default_tenant"
            className="input"
            value={draft.default_tenant}
            onChange={(e) => setDraft({ ...draft, default_tenant: e.target.value })}
          >
            {Object.keys(draft.tenants).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <fieldset className="space-y-3">
        <legend className="text-xs font-semibold uppercase text-muted-foreground">Policy</legend>
        <TagInput
          label="Allowed apps"
          values={policy.allowed_apps}
          onChange={(v) => setPolicy({ allowed_apps: v })}
        />
        <TagInput
          label="Allowed URL patterns"
          values={policy.allowed_url_patterns}
          onChange={(v) => setPolicy({ allowed_url_patterns: v })}
        />
        <TagInput
          label="Allowed action kinds"
          values={policy.allowed_action_kinds}
          onChange={(v) => setPolicy({ allowed_action_kinds: v })}
        />
        <TagInput
          label="Mutating control patterns"
          values={policy.mutating_control_patterns}
          onChange={(v) => setPolicy({ mutating_control_patterns: v })}
        />
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-xs font-semibold uppercase text-muted-foreground">Approvals</legend>
        <div className="flex flex-wrap gap-6 text-sm">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={policy.approval.mutating}
              onChange={(e) => setApproval({ mutating: e.target.checked })}
            />
            Require approval for mutating actions
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={policy.approval.sensitive_export}
              onChange={(e) => setApproval({ sensitive_export: e.target.checked })}
            />
            Require approval for sensitive exports
          </label>
        </div>
        <Field label="Sensitive fill approval" htmlFor="sensitive_fill" className="max-w-xs">
          <select
            id="sensitive_fill"
            className="input"
            value={policy.approval.sensitive_fill}
            onChange={(e) => setApproval({ sensitive_fill: e.target.value as SensitiveFillMode })}
          >
            <option value="literals">literals - only when a literal value is typed</option>
            <option value="always">always</option>
            <option value="off">off</option>
          </select>
        </Field>
        <TagInput
          label="Sensitive field patterns"
          values={policy.approval.sensitive_field_patterns}
          onChange={(v) => setApproval({ sensitive_field_patterns: v })}
        />
      </fieldset>

      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Saving…" : "Save profile"}
      </Button>
    </form>
  );
}
