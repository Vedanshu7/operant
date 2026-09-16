import { useMemo, useState, type FormEvent, type ReactElement } from "react";
import { useNavigate } from "react-router";

import { useProfiles, useStartDiscovery } from "@/api/queries";
import type { DiscoveryRequest } from "@/api/types";
import { rowsToRecord, type InputRow } from "@/lib/inputs";

import { Button } from "./Button";
import { ErrorBox } from "./ErrorBox";
import { Field } from "./Field";
import { InputsEditor } from "./InputsEditor";
import { TenantSelect } from "./TenantSelect";

type Agents = NonNullable<DiscoveryRequest["agents"]>;

const AGENTS: readonly Agents[] = ["single", "multi"];

function isAgents(value: string): value is Agents {
  return AGENTS.some((a) => a === value);
}

const BOOTSTRAP = "__bootstrap__";

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

export function DiscoverForm(): ReactElement {
  const navigate = useNavigate();
  const [goal, setGoal] = useState("");
  const [profileId, setProfileId] = useState<string>(BOOTSTRAP);
  const [tenant, setTenant] = useState("");
  const [capabilityId, setCapabilityId] = useState("");
  const [capabilityName, setCapabilityName] = useState("");
  const [rows, setRows] = useState<InputRow[]>([]);
  const [screenshots, setScreenshots] = useState(true);
  const [agents, setAgents] = useState<Agents>("single");
  const [idTouched, setIdTouched] = useState(false);

  const profiles = useProfiles();
  const discovery = useStartDiscovery();

  const profileTenants = useMemo(
    () => profiles.data?.find((p) => p.id === profileId)?.tenants ?? [],
    [profiles.data, profileId],
  );

  const effectiveCapabilityId = idTouched || capabilityId ? capabilityId : slugify(goal);

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const body: DiscoveryRequest = {
      goal: goal.trim(),
      capability_id: effectiveCapabilityId,
      profile_id: profileId === BOOTSTRAP ? null : profileId,
      inputs: rowsToRecord(rows),
      screenshots,
      agents,
    };
    if (capabilityName.trim()) body.name = capabilityName.trim();
    if (tenant) body.tenant = tenant;
    const run = await discovery.mutateAsync(body);
    await navigate(`/runs/${run.id}`);
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field
        label="Goal"
        htmlFor="goal"
        hint="Describe what the agent should accomplish, in plain language."
      >
        <textarea
          id="goal"
          className="input min-h-28"
          required
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Look up order #1234 and report its shipping status"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Profile" htmlFor="profile">
          <select
            id="profile"
            className="input"
            value={profileId}
            onChange={(e) => {
              setProfileId(e.target.value);
              setTenant("");
            }}
          >
            <option value={BOOTSTRAP}>Bootstrap - no profile (agent picks the app)</option>
            {profiles.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.app_name} ({p.id})
              </option>
            ))}
          </select>
        </Field>
        {/* An app with a single instance has nothing to choose. */}
        {profileTenants.length > 1 && (
          <Field label="Tenant" htmlFor="tenant">
            <TenantSelect
              id="tenant"
              tenants={profileTenants}
              value={tenant}
              onChange={setTenant}
              defaultLabel="Default"
            />
          </Field>
        )}
        <Field
          label="Capability id"
          htmlFor="capability_id"
          hint="Derived from the goal unless you override it."
        >
          <input
            id="capability_id"
            className="input font-mono"
            required
            value={effectiveCapabilityId}
            onChange={(e) => {
              setIdTouched(true);
              setCapabilityId(e.target.value);
            }}
          />
        </Field>
        <Field label="Capability name" htmlFor="capability_name">
          <input
            id="capability_name"
            className="input"
            value={capabilityName}
            onChange={(e) => setCapabilityName(e.target.value)}
            placeholder="Optional display name"
          />
        </Field>
      </div>
      <Field
        label="Inputs"
        hint="Values the agent should use; they become typed capability inputs."
      >
        <InputsEditor rows={rows} onChange={setRows} />
      </Field>
      <Field
        label="Agents"
        htmlFor="agents"
        hint="Multi-agent adds a planner and a verifier panel that checks each step."
      >
        <select
          id="agents"
          className="input"
          value={agents}
          onChange={(e) => {
            if (isAgents(e.target.value)) setAgents(e.target.value);
          }}
        >
          <option value="single">Single agent</option>
          <option value="multi">Multi-agent (planner, executor, verifier)</option>
        </select>
      </Field>
      <div className="flex flex-wrap gap-6 text-sm">
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={screenshots}
            onChange={(e) => setScreenshots(e.target.checked)}
          />
          Save screenshots
        </label>
      </div>
      <ErrorBox error={discovery.error} />
      <Button type="submit" variant="primary" disabled={discovery.isPending || goal.trim() === ""}>
        {discovery.isPending ? "Starting…" : "Start discovery"}
      </Button>
    </form>
  );
}
