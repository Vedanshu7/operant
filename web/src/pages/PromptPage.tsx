import type { ReactElement } from "react";

import { Boxes, ShieldCheck, Sparkles } from "lucide-react";

import { Card } from "@/components/Card";
import { GoalForm } from "@/components/GoalForm";
import { PageHeader } from "@/components/PageHeader";

const HINTS = [
  {
    icon: Sparkles,
    title: "Discover",
    body: "Describe a goal in plain language; the agent drives the app and records a replayable capability.",
  },
  {
    icon: Boxes,
    title: "Replay",
    body: "Pick an existing capability and run it deterministically against any bound tenant.",
  },
  {
    icon: ShieldCheck,
    title: "Stay in control",
    body: "Risky, mutating, and sensitive steps pause here for your approval before they run.",
  },
];

export function PromptPage(): ReactElement {
  return (
    <div>
      <PageHeader
        title="New run"
        description="Start a discovery from a goal, or replay a saved capability."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Card title="What should Operant do?">
          <GoalForm />
        </Card>
        <div className="space-y-3">
          {HINTS.map((h) => (
            <div
              key={h.title}
              className="flex gap-3 rounded-xl border border-border bg-card p-4 shadow-sm"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <h.icon className="size-4" />
              </span>
              <div className="space-y-0.5">
                <p className="text-sm font-medium">{h.title}</p>
                <p className="text-xs text-muted-foreground">{h.body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
