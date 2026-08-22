import type { ReactElement } from "react";

import { KeyRound } from "lucide-react";

import { useCheckSecretRef, useDeleteSecretRef, useSecretRefs } from "@/api/queries";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox } from "@/components/ErrorBox";
import { Loading } from "@/components/Loading";
import { PageHeader } from "@/components/PageHeader";
import { PresenceDot } from "@/components/PresenceDot";
import { SecretRefForm } from "@/components/SecretRefForm";
import { formatTime } from "@/lib/format";

export function SecretsPage(): ReactElement {
  const refs = useSecretRefs();
  const check = useCheckSecretRef();
  const del = useDeleteSecretRef();
  return (
    <div className="space-y-5">
      <PageHeader
        title="Secrets"
        description="Operant never stores or displays secret values. A reference names where the value lives (an environment variable or a Keychain item); the driver resolves it at fill time."
      />
      <ErrorBox error={refs.error ?? check.error ?? del.error} />
      <div className="rounded-xl border border-border bg-card p-1 shadow-sm">
        {refs.isPending && <Loading />}
        {refs.data && refs.data.length === 0 && (
          <EmptyState
            icon={<KeyRound />}
            title="No secret references yet"
            description="Add one below to bind a name the model can use to a value the driver resolves."
          />
        )}
        {refs.data && refs.data.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Backend</th>
                <th>Locator</th>
                <th>Present</th>
                <th>Last checked</th>
                <th>Description</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {refs.data.map((r) => (
                <tr key={r.name}>
                  <td className="font-mono text-xs">{r.name}</td>
                  <td>
                    <Badge>{r.backend}</Badge>
                  </td>
                  <td className="font-mono text-xs">{r.locator}</td>
                  <td>
                    <PresenceDot present={r.present} />
                  </td>
                  <td className="text-xs text-muted-foreground">{formatTime(r.last_checked_at)}</td>
                  <td className="text-xs">{r.description}</td>
                  <td className="space-x-1 whitespace-nowrap text-right">
                    <Button
                      size="sm"
                      disabled={check.isPending}
                      onClick={() => check.mutate(r.name)}
                    >
                      Check
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={del.isPending}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Delete secret reference "${r.name}"? The underlying value is not touched.`,
                          )
                        ) {
                          del.mutate(r.name);
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Card title="Add a reference">
        <SecretRefForm />
      </Card>
    </div>
  );
}
