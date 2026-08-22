import { useState, type FormEvent, type ReactElement } from "react";

import { useCreateSecretRef } from "@/api/queries";
import type { SecretBackend } from "@/api/types";

import { Button } from "./Button";
import { ErrorBox } from "./ErrorBox";
import { Field } from "./Field";

export function SecretRefForm(): ReactElement {
  const [name, setName] = useState("");
  const [backend, setBackend] = useState<SecretBackend>("env");
  const [locator, setLocator] = useState("");
  const [description, setDescription] = useState("");
  const create = useCreateSecretRef();

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        backend,
        locator: locator.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
      },
      {
        onSuccess: () => {
          setName("");
          setLocator("");
          setDescription("");
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-5 sm:items-start">
      <Field label="Name" htmlFor="secret_name">
        <input
          id="secret_name"
          className="input font-mono"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Backend" htmlFor="secret_backend">
        <select
          id="secret_backend"
          className="input"
          value={backend}
          onChange={(e) => setBackend(e.target.value as SecretBackend)}
        >
          <option value="env">env</option>
          <option value="keychain">keychain</option>
        </select>
      </Field>
      <Field
        label="Locator"
        htmlFor="secret_locator"
        hint={backend === "env" ? "Environment variable name" : "Keychain service/account"}
      >
        <input
          id="secret_locator"
          className="input font-mono"
          required
          value={locator}
          onChange={(e) => setLocator(e.target.value)}
        />
      </Field>
      <Field label="Description" htmlFor="secret_description">
        <input
          id="secret_description"
          className="input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <div>
        <span className="label invisible hidden sm:block" aria-hidden="true">
          &nbsp;
        </span>
        <Button
          type="submit"
          variant="primary"
          disabled={create.isPending}
          className="w-full justify-center"
        >
          Add ref
        </Button>
      </div>
      <ErrorBox error={create.error} className="sm:col-span-5" />
    </form>
  );
}
