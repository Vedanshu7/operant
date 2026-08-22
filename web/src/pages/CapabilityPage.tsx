import { useState, type ReactElement } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  useApproveCapability,
  useCapability,
  useCapabilityGraph,
  useInvokeCapability,
} from "@/api/queries";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorBox } from "@/components/ErrorBox";
import { GraphView } from "@/components/GraphView";
import { InvokeForm } from "@/components/InvokeForm";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";
import { StabilityBar } from "@/components/StabilityBar";
import { formatTime } from "@/lib/format";

export function CapabilityPage(): ReactElement {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const cap = useCapability(id);
  const graph = useCapabilityGraph(id);
  const approve = useApproveCapability(id);
  const invoke = useInvokeCapability(id);
  const [force, setForce] = useState(false);
  const [tenant, setTenant] = useState("");

  if (cap.isPending) return <Loading />;
  if (cap.error || !cap.data) return <ErrorBox error={cap.error ?? "Capability not found"} />;
  const c = cap.data;
  const canApprove = c.status !== "approved" && (c.gate.passes || force);
  const gateTooltip = c.gate.passes
    ? undefined
    : `Stability gate not met: ${c.stability.successes}/${c.stability.runs} runs, need ${c.gate.min_runs} at ${Math.round(c.gate.min_success_rate * 100)}%`;

  return (
    <div className="space-y-4">
      <PageHeader
        title={c.name}
        description={
          <>
            <span className="font-mono text-xs">{c.id}</span>
            <span className="mt-1 block text-foreground">{c.description}</span>
          </>
        }
        actions={
          <>
            <Badge>v{c.version}</Badge>
            <Badge
              className={
                c.status === "approved" ? "border-transparent bg-success/15 text-success" : ""
              }
            >
              {c.status}
            </Badge>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Stability and approval">
          <StabilityBar stability={c.stability} gate={c.gate} />
          <p className="mt-1 text-xs text-muted-foreground">
            last run {formatTime(c.stability.last_run_at)}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span title={gateTooltip}>
              <Button
                variant="primary"
                disabled={!canApprove || approve.isPending}
                onClick={() => approve.mutate({ force })}
              >
                {c.status === "approved" ? "Approved" : "Approve"}
              </Button>
            </span>
            {c.status !== "approved" && !c.gate.passes && (
              <label className="inline-flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(e) => setForce(e.target.checked)}
                />
                force (bypass stability gate)
              </label>
            )}
          </div>
          {gateTooltip && c.status !== "approved" && (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">{gateTooltip}</p>
          )}
          <ErrorBox error={approve.error} className="mt-2" />
        </Card>

        <Card title="Provenance">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted-foreground">discovery run</dt>
            <dd>
              <Link
                to={`/runs/${c.provenance.discovery_run_id}`}
                className="font-mono text-primary hover:underline"
              >
                {c.provenance.discovery_run_id}
              </Link>
            </dd>
            <dt className="text-muted-foreground">model</dt>
            <dd className="font-mono">{c.provenance.model}</dd>
            <dt className="text-muted-foreground">recorded</dt>
            <dd>{formatTime(c.provenance.recorded_at)}</dd>
            <dt className="text-muted-foreground">goal</dt>
            <dd>{c.provenance.goal}</dd>
            <dt className="text-muted-foreground">vendor</dt>
            <dd>{c.vendor_id}</dd>
            <dt className="text-muted-foreground">graph</dt>
            <dd>
              v{c.graph_version} · {c.start_node} → {c.goal_node}
            </dd>
          </dl>
        </Card>

        <Card title="Inputs">
          {Object.keys(c.inputs).length === 0 ? (
            <p className="text-sm text-muted-foreground">None</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Flags</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(c.inputs).map(([name, f]) => (
                  <tr key={name}>
                    <td className="font-mono text-xs">{name}</td>
                    <td className="text-xs">{f.type}</td>
                    <td className="space-x-1">
                      {f.required && <Badge>required</Badge>}
                      {f.sensitive && (
                        <Badge className="bg-fuchsia-100 text-fuchsia-900 dark:bg-fuchsia-900 dark:text-fuchsia-100">
                          sensitive
                        </Badge>
                      )}
                      {f.data_class !== "none" && <Badge>{f.data_class}</Badge>}
                    </td>
                    <td className="text-xs">{f.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Outputs">
          {Object.keys(c.outputs).length === 0 ? (
            <p className="text-sm text-muted-foreground">None</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Data class</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(c.outputs).map(([name, o]) => (
                  <tr key={name}>
                    <td className="font-mono text-xs">{name}</td>
                    <td className="text-xs">{o.data_class}</td>
                    <td className="text-xs">{o.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title="Compiled path">
        <ol className="flex flex-wrap items-center gap-1 font-mono text-xs">
          {c.compiled_path.map((n, i) => (
            <li key={`${n}-${i}`} className="flex items-center gap-1">
              <span className="rounded border border-zinc-200 px-1.5 py-0.5 dark:border-zinc-800">
                {n}
              </span>
              {i < c.compiled_path.length - 1 && <span className="text-muted-foreground">→</span>}
            </li>
          ))}
        </ol>
      </Card>

      <Card title="Invoke">
        <div className="mb-3 max-w-xs">
          <label className="label" htmlFor="invoke_tenant">
            Tenant
          </label>
          <select
            id="invoke_tenant"
            className="input"
            value={tenant}
            onChange={(e) => setTenant(e.target.value)}
          >
            <option value="">Default ({c.default_tenant})</option>
            {Object.keys(c.tenants).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <InvokeForm
          fields={c.inputs}
          busy={invoke.isPending}
          onSubmit={(inputs) =>
            invoke.mutate(
              { inputs, ...(tenant ? { tenant } : {}) },
              { onSuccess: (run) => void navigate(`/runs/${run.id}`) },
            )
          }
        />
        <ErrorBox error={invoke.error} className="mt-2" />
      </Card>

      <Card title="Graph">
        {graph.isPending && <Loading />}
        <ErrorBox error={graph.error} />
        {graph.data && <GraphView graph={graph.data} highlightPath={c.compiled_path} />}
      </Card>
    </div>
  );
}
