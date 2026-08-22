import type { ReactElement } from "react";

import type { AppGraph, GraphEdge, GraphNode } from "@/api/types";

import { JsonBlock } from "./JsonBlock";

export interface GraphViewProps {
  graph: AppGraph;
  highlightPath?: string[];
}

function asId(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "?";
}

function describe(obj: GraphNode | GraphEdge, skip: string[]): string {
  return Object.entries(obj)
    .filter(([k, v]) => !skip.includes(k) && (typeof v === "string" || typeof v === "number"))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join("  ");
}

export function GraphView({ graph, highlightPath = [] }: GraphViewProps): ReactElement {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  const onPath = new Set(highlightPath);
  if (nodes.length === 0 && edges.length === 0) return <JsonBlock value={graph} />;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Nodes ({nodes.length})
        </h3>
        <ul className="space-y-1 text-xs">
          {nodes.map((n) => (
            <li
              key={n.id}
              className={`rounded border px-2 py-1 ${onPath.has(n.id) ? "border-primary/50 bg-primary/10" : "border-border"}`}
            >
              <span className="font-mono font-semibold">{n.id}</span>
              <span className="ml-2 text-muted-foreground">{describe(n, ["id"])}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Edges ({edges.length})
        </h3>
        <ul className="space-y-1 text-xs">
          {edges.map((e, i) => {
            const from = asId(e.from ?? e.source);
            const to = asId(e.to);
            return (
              <li key={e.id ?? i} className="rounded border border-border px-2 py-1">
                <span className="font-mono">
                  {e.id && <span className="font-semibold">{e.id} </span>}
                  {from} → {to}
                </span>
                <span className="ml-2 text-muted-foreground">
                  {describe(e, ["id", "from", "to", "source", "target"])}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
