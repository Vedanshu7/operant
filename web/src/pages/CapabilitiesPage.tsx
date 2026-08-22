import type { ReactElement } from "react";

import { Boxes, CheckCircle2, FileText } from "lucide-react";
import { Link } from "react-router";

import { useCapabilities } from "@/api/queries";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox } from "@/components/ErrorBox";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";
import { StabilityBar } from "@/components/StabilityBar";

export function CapabilitiesPage(): ReactElement {
  const caps = useCapabilities();
  return (
    <div>
      <PageHeader
        title="Capabilities"
        description="Discovered tasks compiled into typed, versioned artifacts you can replay deterministically."
      />
      {caps.isPending && <Loading />}
      <ErrorBox error={caps.error} />
      {caps.data && caps.data.length === 0 && (
        <EmptyState
          icon={<Boxes />}
          title="No capabilities yet"
          description="Run a discovery from the Prompt page and it will be compiled into a capability here."
          action={
            <Link to="/" className="text-sm font-medium text-primary hover:underline">
              Go to Prompt
            </Link>
          }
        />
      )}
      {caps.data && caps.data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {caps.data.map((c) => (
            <Link
              key={c.id}
              to={`/capabilities/${c.id}`}
              className="group flex flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:border-primary/40 hover:bg-accent/40"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <FileText className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-medium group-hover:text-primary">{c.name}</p>
                    <p className="truncate font-mono text-xs text-muted-foreground">{c.id}</p>
                  </div>
                </div>
                <Badge
                  className={
                    c.status === "approved" ? "border-transparent bg-success/15 text-success" : ""
                  }
                >
                  {c.status === "approved" && <CheckCircle2 className="size-3" />}
                  {c.status}
                </Badge>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{c.vendor_id}</span>
                <span className="font-mono">
                  v{c.version} / g{c.graph_version}
                </span>
              </div>
              <StabilityBar stability={c.stability} gate={c.gate} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
