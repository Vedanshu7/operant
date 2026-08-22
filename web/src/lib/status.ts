import type { ApprovalKind, RunStatus } from "@/api/types";

export const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "succeeded",
  "business_outcome",
  "escalated",
  "failed",
  "cancelled",
]);

export const WAITING_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "waiting_approval",
  "waiting_intervention",
  "waiting_clarification",
]);

export const RUN_STATUSES: readonly RunStatus[] = [
  "queued",
  "waiting_driver",
  "running",
  "waiting_approval",
  "waiting_intervention",
  "waiting_clarification",
  "succeeded",
  "business_outcome",
  "escalated",
  "failed",
  "cancelled",
];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function isWaitingForHuman(status: RunStatus): boolean {
  return WAITING_STATUSES.has(status);
}

const STATUS_CLASSES: Record<RunStatus, string> = {
  queued: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100",
  waiting_driver: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100",
  waiting_approval: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
  waiting_intervention: "bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100",
  waiting_clarification: "bg-violet-100 text-violet-900 dark:bg-violet-900 dark:text-violet-100",
  succeeded: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100",
  business_outcome: "bg-teal-100 text-teal-900 dark:bg-teal-900 dark:text-teal-100",
  escalated: "bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100",
  failed: "bg-red-100 text-red-900 dark:bg-red-900 dark:text-red-100",
  cancelled: "bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300",
};

export function statusClasses(status: RunStatus): string {
  return STATUS_CLASSES[status];
}

export function statusLabel(status: RunStatus): string {
  return status.replace(/_/g, " ");
}

const APPROVAL_KIND_CLASSES: Record<ApprovalKind, string> = {
  scope: "bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100",
  mutating: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
  sensitive_fill: "bg-fuchsia-100 text-fuchsia-900 dark:bg-fuchsia-900 dark:text-fuchsia-100",
  sensitive_export: "bg-red-100 text-red-900 dark:bg-red-900 dark:text-red-100",
};

export function approvalKindClasses(kind: ApprovalKind): string {
  return APPROVAL_KIND_CLASSES[kind];
}

export function approvalKindLabel(kind: ApprovalKind): string {
  return kind.replace(/_/g, " ");
}
