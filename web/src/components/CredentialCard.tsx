import { useState, type FormEvent, type ReactElement } from "react";

import { useAnswerCredential } from "@/api/queries";
import type { CredentialRequest } from "@/api/types";

import { Button } from "./Button";
import { Card } from "./Card";
import { ErrorBox } from "./ErrorBox";

export interface CredentialCardProps {
  credential: CredentialRequest;
}

type Mode = "value" | "source";

export function CredentialCard({ credential }: CredentialCardProps): ReactElement {
  const [mode, setMode] = useState<Mode>("value");
  const [value, setValue] = useState("");
  const [locator, setLocator] = useState("");
  const reply = useAnswerCredential();
  const entry = mode === "value" ? value : locator;
  const submit = (e: FormEvent): void => {
    e.preventDefault();
    if (entry.trim() === "") return;
    const body = mode === "value" ? { value: value.trim() } : { locator: locator.trim() };
    reply.mutate({ id: credential.request_id, ...body });
  };
  return (
    <Card
      title={`The agent needs a credential: ${credential.name}`}
      className="border-amber-300 dark:border-amber-700"
    >
      <form onSubmit={submit} className="space-y-3">
        {credential.reason && <p className="text-sm text-muted-foreground">{credential.reason}</p>}
        <p className="text-xs text-muted-foreground">
          The value is sent straight to the run and never shown to the model or saved.
        </p>
        <div className="flex gap-2 text-sm">
          <button
            type="button"
            className={mode === "value" ? "font-semibold text-primary" : "text-muted-foreground"}
            onClick={() => setMode("value")}
          >
            Enter a value
          </button>
          <span className="text-muted-foreground">/</span>
          <button
            type="button"
            className={mode === "source" ? "font-semibold text-primary" : "text-muted-foreground"}
            onClick={() => setMode("source")}
          >
            Use a source (env / keychain)
          </button>
        </div>
        {mode === "value" ? (
          <input
            aria-label="Credential value"
            type="password"
            className="input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={`value for ${credential.name}`}
          />
        ) : (
          <input
            aria-label="Credential source"
            className="input"
            value={locator}
            onChange={(e) => setLocator(e.target.value)}
            placeholder="env:MY_VAR or keychain:service/account"
          />
        )}
        <ErrorBox error={reply.error} />
        <Button type="submit" variant="primary" disabled={reply.isPending || entry.trim() === ""}>
          Provide credential
        </Button>
      </form>
    </Card>
  );
}
