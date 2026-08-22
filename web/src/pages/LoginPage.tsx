import { useState, type FormEvent, type ReactElement } from "react";

import { Zap } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router";

import { Button } from "@/components/Button";
import { Field } from "@/components/Field";
import { getToken, setToken } from "@/lib/auth";

const DEV_TOKEN = "operant-dev";

export function LoginPage(): ReactElement {
  const [token, setTokenValue] = useState(getToken() ?? "");
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    setToken(token.trim());
    const next = params.get("next");
    void navigate(next && next.startsWith("/") ? next : "/", { replace: true });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-md">
            <Zap className="size-6" />
          </span>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Operant</h1>
            <p className="text-sm text-muted-foreground">Computer-use automation console</p>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <form onSubmit={submit} className="space-y-4">
            <Field
              label="API token"
              htmlFor="token"
              hint="Stored in this browser only (localStorage: operant.token)."
            >
              <input
                id="token"
                type="password"
                className="input font-mono"
                autoComplete="off"
                required
                value={token}
                onChange={(e) => setTokenValue(e.target.value)}
              />
            </Field>
            {import.meta.env.DEV && (
              <p className="text-xs text-muted-foreground">
                Dev token:{" "}
                <button
                  type="button"
                  onClick={() => setTokenValue(DEV_TOKEN)}
                  className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground hover:bg-accent"
                >
                  {DEV_TOKEN}
                </button>{" "}
                (click to fill)
              </p>
            )}
            <Button type="submit" variant="primary" className="w-full justify-center">
              Continue
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
