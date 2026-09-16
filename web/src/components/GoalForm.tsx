import { useState, type ReactElement } from "react";

import { DiscoverForm } from "./DiscoverForm";
import { ReplayForm } from "./ReplayForm";

type Mode = "discover" | "replay";

const MODES: readonly Mode[] = ["discover", "replay"];

export function GoalForm(): ReactElement {
  const [mode, setMode] = useState<Mode>("discover");

  return (
    <div className="space-y-4">
      <div role="tablist" className="inline-flex rounded-lg border border-border bg-muted p-1">
        {MODES.map((m) => (
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
      {mode === "discover" ? <DiscoverForm /> : <ReplayForm />}
    </div>
  );
}
