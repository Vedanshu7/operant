import { useMemo, useState, type FormEvent, type ReactElement } from "react";
import { useNavigate } from "react-router";

import {
  useCapabilities,
  useCapability,
  useProfiles,
  useStartDiscovery,
  useStartReplay,
} from "@/api/queries";
import type { DiscoveryRequest, ReplayRequest } from "@/api/types";
import { rowsToRecord, type InputRow } from "@/lib/inputs";

import { Button } from "./Button";
import { ErrorBox } from "./ErrorBox";
import { Field } from "./Field";
import { InputsEditor } from "./InputsEditor";
import { InvokeForm } from "./InvokeForm";

type Mode = "discover" | "replay";

const BOOTSTRAP = "__bootstrap__";

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

export function GoalForm(): ReactElement {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("discover");
  const [goal, setGoal] = useState("");
  const [profileId, setProfileId] = useState<string>(BOOTSTRAP);
  const [tenant, setTenant] = useState("");
  const [capabilityId, setCapabilityId] = useState("");
  const [capabilityName, setCapabilityName] = useState("");
  const [rows, setRows] = useState<InputRow[]>([]);
  const [screenshots, setScreenshots] = useState(true);
  const [capture, setCapture] = useState(false);
  const [replayCapability, setReplayCapability] = useState("");
  const [replayTenant, setReplayTenant] = useState("");
  const [freshSession, setFreshSession] = useState(false);
  const [injectEdge, setInjectEdge] = useState("");
  const [idTouched, setIdTouched] = useState(false);

  const profiles = useProfiles();
  const capabilities = useCapabilities();
  const selectedCapability = useCapability(
    mode === "replay" && replayCapability ? replayCapability : null,
  );
  const discovery = useStartDiscovery();
  const replay = useStartReplay();

  const profileTenants = useMemo(
    () => profiles.data?.find((p) => p.id === profileId)?.tenants ?? [],
    [profiles.data, profileId],
  );

  const effectiveCapabilityId = idTouched || capabilityId ? capabilityId : slugify(goal);

  const submitDiscovery = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const body: DiscoveryRequest = {
      goal: goal.trim(),
      capability_id: effectiveCapabilityId,
      profile_id: profileId === BOOTSTRAP ? null : profileId,
      inputs: rowsToRecord(rows),
      screenshots,
      capture,
    };
    if (capabilityName.trim()) body.name = capabilityName.trim();
    if (tenant) body.tenant = tenant;
    const run = await discovery.mutateAsync(body);
    await navigate(`/runs/${run.id}`);
  };

  const submitReplay = async (inputs: Record<string, string>): Promise<void> => {
    const body: ReplayRequest = {
      capability_id: replayCapability,
      inputs,
      fresh_session: freshSession,
    };
    if (replayTenant) body.tenant = replayTenant;
    if (injectEdge.trim()) body.inject_session_expiry_before = injectEdge.trim();
    const run = await replay.mutateAsync(body);
    await navigate(`/runs/${run.id}`);
  };

  const tenantOptions = selectedCapability.data ? Object.keys(selectedCapability.data.tenants) : [];

  return (
    <div className="space-y-4">
      <div role="tablist" className="inline-flex rounded-lg border border-border bg-muted p-1">
        {(["discover", "replay"] as const).map((m) => (
          <button
            key={m}
            role="tab"
            type="button"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1 text-sm font-medium capitalize transition-colors ${
              mode === m
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === "discover" ? (
        <form onSubmit={submitDiscovery} className="space-y-4">
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
              placeholder="Transfer $25 from checking to savings and tell me the new balance"
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
            <Field label="Tenant" htmlFor="tenant">
              <select
                id="tenant"
                className="input"
                value={tenant}
                disabled={profileTenants.length === 0}
                onChange={(e) => setTenant(e.target.value)}
              >
                <option value="">Default</option>
                {profileTenants.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
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
          <div className="flex flex-wrap gap-6 text-sm">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={screenshots}
                onChange={(e) => setScreenshots(e.target.checked)}
              />
              Save screenshots
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={capture}
                onChange={(e) => setCapture(e.target.checked)}
              />
              Full UI capture (screen + input)
            </label>
          </div>
          <ErrorBox error={discovery.error} />
          <Button
            type="submit"
            variant="primary"
            disabled={discovery.isPending || goal.trim() === ""}
          >
            {discovery.isPending ? "Starting…" : "Start discovery"}
          </Button>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Capability" htmlFor="replay_capability">
              <select
                id="replay_capability"
                className="input"
                value={replayCapability}
                onChange={(e) => {
                  setReplayCapability(e.target.value);
                  setReplayTenant("");
                }}
              >
                <option value="">Select a capability…</option>
                {capabilities.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} - {c.id} v{c.version} ({c.status})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Tenant" htmlFor="replay_tenant">
              <select
                id="replay_tenant"
                className="input"
                value={replayTenant}
                disabled={tenantOptions.length === 0}
                onChange={(e) => setReplayTenant(e.target.value)}
              >
                <option value="">
                  Default
                  {selectedCapability.data ? ` (${selectedCapability.data.default_tenant})` : ""}
                </option>
                {tenantOptions.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={freshSession}
              onChange={(e) => setFreshSession(e.target.checked)}
            />
            Fresh session (discard saved login state)
          </label>
          <Field label="Inject session expiry before edge (optional)" htmlFor="inject_edge">
            <input
              id="inject_edge"
              className="input"
              value={injectEdge}
              onChange={(e) => setInjectEdge(e.target.value)}
              placeholder="edge id, e.g. edge-2-3 — forces an error run"
            />
          </Field>
          {selectedCapability.data && (
            <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
              <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Inputs</h3>
              <InvokeForm
                key={selectedCapability.data.id}
                fields={selectedCapability.data.inputs}
                onSubmit={submitReplay}
                submitLabel="Start replay"
                busy={replay.isPending}
              />
            </div>
          )}
          <ErrorBox error={replay.error ?? selectedCapability.error} />
        </div>
      )}
    </div>
  );
}
