import type { ReactElement } from "react";

import { AppWindow, SlidersHorizontal } from "lucide-react";
import { Link } from "react-router";

import { useProfiles } from "@/api/queries";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox } from "@/components/ErrorBox";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";

export function ProfilesPage(): ReactElement {
  const profiles = useProfiles();
  return (
    <div>
      <PageHeader
        title="Profiles"
        description="Per-app knowledge shared by every capability: allowlists, mutating-control patterns, and tenant bindings."
      />
      {profiles.isPending && <Loading />}
      <ErrorBox error={profiles.error} />
      {profiles.data && profiles.data.length === 0 && (
        <EmptyState icon={<SlidersHorizontal />} title="No profiles yet" />
      )}
      {profiles.data && profiles.data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {profiles.data.map((p) => (
            <Link
              key={p.id}
              to={`/profiles/${p.id}`}
              className="group flex flex-col gap-3 rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:border-primary/40 hover:bg-accent/40"
            >
              <div className="flex items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <AppWindow className="size-5" />
                </span>
                <div className="min-w-0">
                  <p className="truncate font-medium group-hover:text-primary">{p.app_name}</p>
                  <p className="truncate font-mono text-xs text-muted-foreground">{p.id}</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Tenants:</span>
                {p.tenants.length === 0 && (
                  <span className="text-xs text-muted-foreground">none</span>
                )}
                {p.tenants.map((t) => (
                  <Badge key={t} className="font-mono normal-case">
                    {t}
                  </Badge>
                ))}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
