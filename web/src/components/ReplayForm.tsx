import { useState, type ReactElement } from "react";
import { useNavigate } from "react-router";

import { useCapabilities, useCapability, useStartReplay } from "@/api/queries";
import type { ReplayRequest } from "@/api/types";

import { ErrorBox } from "./ErrorBox";
import { Field } from "./Field";
import { InvokeForm } from "./InvokeForm";
import { TenantSelect } from "./TenantSelect";

export function ReplayForm(): ReactElement {
  const navigate = useNavigate();
  const [capabilityId, setCapabilityId] = useState("");
  const [tenant, setTenant] = useState("");
  const [injectEdge, setInjectEdge] = useState("");

  const capabilities = useCapabilities();
  const selected = useCapability(capabilityId || null);
  const replay = useStartReplay();

  const submit = async (inputs: Record<string, string>): Promise<void> => {
    const body: ReplayRequest = {
      capability_id: capabilityId,
      inputs,
    };
    if (tenant) body.tenant = tenant;
    if (injectEdge.trim()) body.inject_session_expiry_before = injectEdge.trim();
    const run = await replay.mutateAsync(body);
    await navigate(`/runs/${run.id}`);
  };

  const tenantOptions = selected.data ? Object.keys(selected.data.tenants) : [];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Capability" htmlFor="replay_capability">
          <select
            id="replay_capability"
            className="input"
            value={capabilityId}
            onChange={(e) => {
              setCapabilityId(e.target.value);
              setTenant("");
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
        {tenantOptions.length > 1 && (
          <Field label="Tenant" htmlFor="replay_tenant">
            <TenantSelect
              id="replay_tenant"
              tenants={tenantOptions}
              value={tenant}
              onChange={setTenant}
              defaultLabel={selected.data ? `Default (${selected.data.default_tenant})` : "Default"}
            />
          </Field>
        )}
      </div>
      <Field label="Inject session expiry before edge (optional)" htmlFor="inject_edge">
        <input
          id="inject_edge"
          className="input"
          value={injectEdge}
          onChange={(e) => setInjectEdge(e.target.value)}
          placeholder="edge id, e.g. edge-2-3 — forces an error run"
        />
      </Field>
      {selected.data && (
        <div className="rounded-md border border-border p-3">
          <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Inputs</h3>
          <InvokeForm
            key={selected.data.id}
            fields={selected.data.inputs}
            onSubmit={submit}
            submitLabel="Start replay"
            busy={replay.isPending}
          />
        </div>
      )}
      <ErrorBox error={replay.error ?? selected.error} />
    </div>
  );
}
