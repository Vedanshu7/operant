import type { ReactElement } from "react";

import type { Stability, StabilityGate } from "@/api/types";

export interface StabilityBarProps {
  stability: Stability;
  gate: StabilityGate;
}

export function StabilityBar({ stability, gate }: StabilityBarProps): ReactElement {
  const rate = stability.runs > 0 ? stability.successes / stability.runs : 0;
  const pct = Math.round(rate * 100);
  const threshold = Math.round(gate.min_success_rate * 100);
  const enoughRuns = stability.runs >= gate.min_runs;
  const colour = gate.passes ? "bg-emerald-500" : enoughRuns ? "bg-red-500" : "bg-amber-400";
  return (
    <div
      className="min-w-40"
      title={`${stability.successes}/${stability.runs} succeeded · gate ${gate.min_runs} runs at ${threshold}%`}
    >
      <div className="relative h-2 w-full rounded bg-zinc-200 dark:bg-zinc-700">
        <div className={`h-2 rounded ${colour}`} style={{ width: `${pct}%` }} />
        <div
          className="absolute top-[-3px] h-3.5 w-0.5 bg-zinc-700 dark:bg-zinc-200"
          style={{ left: `${threshold}%` }}
          aria-label={`gate threshold ${threshold}%`}
        />
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        {stability.successes}/{stability.runs} ok ({pct}%) · need {gate.min_runs} runs @ {threshold}
        %
      </p>
    </div>
  );
}
