import { useState, type ReactElement } from "react";
import { useParams } from "react-router";

import { useProfile, useSaveProfile, useSaveTenant, useSecretRefs } from "@/api/queries";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorBox } from "@/components/ErrorBox";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";
import { PresenceDot } from "@/components/PresenceDot";
import { ProfileForm } from "@/components/ProfileForm";
import { TenantEditor } from "@/components/TenantEditor";

export function ProfilePage(): ReactElement {
  const { id = "" } = useParams();
  const profile = useProfile(id);
  const secrets = useSecretRefs();
  const save = useSaveProfile(id);
  const saveTenant = useSaveTenant(id);
  const [editing, setEditing] = useState<string | null>(null);

  if (profile.isPending) return <Loading />;
  if (profile.error || !profile.data)
    return <ErrorBox error={profile.error ?? "Profile not found"} />;
  const p = profile.data;
  const refs = secrets.data ?? [];
  const presence = (name: string): boolean | null =>
    refs.find((r) => r.name === name)?.present ?? null;

  return (
    <div className="space-y-4">
      <PageHeader
        title={p.app_name}
        description={
          <span className="font-mono text-xs">
            {id} · vendor {p.vendor_id}
          </span>
        }
      />
      <Card title="Policy and approvals">
        <ProfileForm
          key={JSON.stringify(p)}
          profile={p}
          onSave={(next) => save.mutate(next)}
          busy={save.isPending}
        />
        <ErrorBox error={save.error} className="mt-2" />
        {save.isSuccess && !save.isPending && <p className="mt-2 text-xs text-success">Saved.</p>}
      </Card>
      <Card title="Tenants">
        <table className="table">
          <thead>
            <tr>
              <th>Tenant</th>
              <th>Base URL</th>
              <th>Entry path</th>
              <th>Secret refs</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {Object.entries(p.tenants).map(([name, t]) => (
              <tr key={name}>
                <td className="font-mono text-xs">
                  {name}
                  {name === p.default_tenant && (
                    <span className="ml-1 text-muted-foreground">(default)</span>
                  )}
                </td>
                <td className="font-mono text-xs">{t.base_url || "-"}</td>
                <td className="font-mono text-xs">{t.entry_path || "-"}</td>
                <td>
                  <ul className="space-y-0.5">
                    {Object.entries(t.secret_refs).map(([field, ref]) => (
                      <li key={field} className="flex items-center gap-2 text-xs">
                        <span className="text-muted-foreground">{field} →</span>
                        <PresenceDot present={presence(ref)} label={ref} />
                      </li>
                    ))}
                    {Object.keys(t.secret_refs).length === 0 && (
                      <li className="text-xs text-muted-foreground">none</li>
                    )}
                  </ul>
                </td>
                <td>
                  <Button size="sm" onClick={() => setEditing(name)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editing && p.tenants[editing] && (
          <div className="mt-3">
            <TenantEditor
              key={editing}
              name={editing}
              binding={p.tenants[editing]}
              secretRefs={refs}
              busy={saveTenant.isPending}
              onCancel={() => setEditing(null)}
              onSave={(tenant, binding) =>
                saveTenant.mutate({ tenant, ...binding }, { onSuccess: () => setEditing(null) })
              }
            />
            <ErrorBox error={saveTenant.error} className="mt-2" />
          </div>
        )}
      </Card>
    </div>
  );
}
