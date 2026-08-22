import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, fetchText } from "@/api/client";
import type {
  AppGraph,
  AppProfile,
  Approval,
  ApprovalDecision,
  CapabilityApproveBody,
  CapabilityDetail,
  CapabilityInvokeBody,
  CapabilitySummary,
  Clarification,
  ClarificationAnswer,
  CredentialAnswer,
  DiscoveryRequest,
  DoctorReport,
  EvidenceListing,
  Health,
  Intervention,
  NoteBody,
  ProfileSummary,
  ReplayRequest,
  RunDetail,
  RunList,
  RunListFilters,
  RunSummary,
  SecretRef,
  SecretRefCreate,
  TenantBinding,
} from "@/api/types";
import { isTerminal } from "@/lib/status";

export const keys = {
  runs: (filters: RunListFilters) => ["runs", filters] as const,
  run: (id: string) => ["run", id] as const,
  pendingApprovals: ["approvals", "pending"] as const,
  capabilities: ["capabilities"] as const,
  capability: (id: string) => ["capability", id] as const,
  capabilityGraph: (id: string) => ["capability", id, "graph"] as const,
  profiles: ["profiles"] as const,
  profile: (id: string) => ["profile", id] as const,
  secretRefs: ["secrets", "refs"] as const,
  evidence: (runId: string) => ["evidence", runId] as const,
  evidenceFile: (runId: string, path: string) => ["evidence", runId, path] as const,
  health: ["health"] as const,
  doctor: ["doctor"] as const,
};

export function useRuns(filters: RunListFilters) {
  return useQuery({
    queryKey: keys.runs(filters),
    queryFn: () => fetchJson<RunList>("/runs", { query: { ...filters } }),
    refetchInterval: 10_000,
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: keys.run(id),
    queryFn: () => fetchJson<RunDetail>(`/runs/${id}`),
    refetchInterval: (q) => (q.state.data && isTerminal(q.state.data.status) ? false : 5_000),
  });
}

export function useStartDiscovery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DiscoveryRequest) =>
      fetchJson<RunSummary>("/runs/discovery", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useStartReplay() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReplayRequest) =>
      fetchJson<RunSummary>("/runs/replay", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useCancelRun(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => fetchJson<RunSummary>(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.run(id) }),
  });
}

export function usePendingApprovals() {
  return useQuery({
    queryKey: keys.pendingApprovals,
    queryFn: () => fetchJson<Approval[]>("/approvals", { query: { status: "pending" } }),
    refetchInterval: 5_000,
  });
}

export function useDecideApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: ApprovalDecision & { id: string }) =>
      fetchJson<Approval>(`/approvals/${id}`, { method: "POST", body }),
    onSuccess: (approval) => {
      void qc.invalidateQueries({ queryKey: keys.pendingApprovals });
      void qc.invalidateQueries({ queryKey: keys.run(approval.run_id) });
    },
  });
}

export type InterventionAction = "take" | "handback" | "abandon";

export function useInterventionAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, ...body }: NoteBody & { id: string; action: InterventionAction }) =>
      fetchJson<Intervention>(`/interventions/${id}/${action}`, { method: "POST", body }),
    onSuccess: (iv) => qc.invalidateQueries({ queryKey: keys.run(iv.run_id) }),
  });
}

export function useAnswerClarification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: ClarificationAnswer & { id: string }) =>
      fetchJson<Clarification>(`/clarifications/${id}`, { method: "POST", body }),
    onSuccess: (c) => qc.invalidateQueries({ queryKey: keys.run(c.run_id) }),
  });
}

export function useAnswerCredential() {
  return useMutation({
    mutationFn: ({ id, ...body }: CredentialAnswer & { id: string }) =>
      fetchJson<{ ok: boolean }>(`/credentials/${id}`, { method: "POST", body }),
  });
}

export function useCapabilities() {
  return useQuery({
    queryKey: keys.capabilities,
    queryFn: () => fetchJson<CapabilitySummary[]>("/capabilities"),
  });
}

export function useCapability(id: string | null) {
  return useQuery({
    queryKey: keys.capability(id ?? ""),
    queryFn: () => fetchJson<CapabilityDetail>(`/capabilities/${id ?? ""}`),
    enabled: id !== null && id !== "",
  });
}

export function useCapabilityGraph(id: string) {
  return useQuery({
    queryKey: keys.capabilityGraph(id),
    queryFn: () => fetchJson<AppGraph>(`/capabilities/${id}/graph`),
  });
}

export function useApproveCapability(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CapabilityApproveBody) =>
      fetchJson<CapabilityDetail>(`/capabilities/${id}/approve`, { method: "POST", body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.capability(id) });
      void qc.invalidateQueries({ queryKey: keys.capabilities });
    },
  });
}

export function useInvokeCapability(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CapabilityInvokeBody) =>
      fetchJson<RunSummary>(`/capabilities/${id}/invoke`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useProfiles() {
  return useQuery({
    queryKey: keys.profiles,
    queryFn: () => fetchJson<ProfileSummary[]>("/profiles"),
  });
}

export function useProfile(id: string | null) {
  return useQuery({
    queryKey: keys.profile(id ?? ""),
    queryFn: () => fetchJson<AppProfile>(`/profiles/${id ?? ""}`),
    enabled: id !== null && id !== "",
  });
}

export function useSaveProfile(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AppProfile) =>
      fetchJson<AppProfile>(`/profiles/${id}`, { method: "PUT", body }),
    onSuccess: (profile) => {
      qc.setQueryData(keys.profile(id), profile);
      void qc.invalidateQueries({ queryKey: keys.profiles });
    },
  });
}

export function useSaveTenant(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ tenant, ...body }: TenantBinding & { tenant: string }) =>
      fetchJson<AppProfile>(`/profiles/${id}/tenants/${encodeURIComponent(tenant)}`, {
        method: "PUT",
        body,
      }),
    onSuccess: (profile) => {
      qc.setQueryData(keys.profile(id), profile);
      void qc.invalidateQueries({ queryKey: keys.profiles });
    },
  });
}

export function useSecretRefs() {
  return useQuery({
    queryKey: keys.secretRefs,
    queryFn: () => fetchJson<SecretRef[]>("/secrets/refs"),
  });
}

export function useCreateSecretRef() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SecretRefCreate) =>
      fetchJson<SecretRef>("/secrets/refs", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.secretRefs }),
  });
}

export function useDeleteSecretRef() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      fetchJson<undefined>(`/secrets/refs/${encodeURIComponent(name)}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.secretRefs }),
  });
}

export function useCheckSecretRef() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      fetchJson<SecretRef>(`/secrets/refs/${encodeURIComponent(name)}/check`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.secretRefs }),
  });
}

export function useEvidence(runId: string) {
  return useQuery({
    queryKey: keys.evidence(runId),
    queryFn: () => fetchJson<EvidenceListing>(`/evidence/${runId}`),
  });
}

export function useEvidenceText(runId: string, path: string | null) {
  return useQuery({
    queryKey: keys.evidenceFile(runId, path ?? ""),
    queryFn: () => fetchText(`/evidence/${runId}/files/${path ?? ""}`),
    enabled: path !== null,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => fetchJson<Health>("/health"),
    refetchInterval: 30_000,
    retry: false,
  });
}

export function useDoctor() {
  return useQuery({ queryKey: keys.doctor, queryFn: () => fetchJson<DoctorReport>("/doctor") });
}
