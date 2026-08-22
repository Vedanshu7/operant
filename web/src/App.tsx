import type { ReactElement } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { Layout } from "@/components/Layout";
import { getToken } from "@/lib/auth";
import { CapabilitiesPage } from "@/pages/CapabilitiesPage";
import { CapabilityPage } from "@/pages/CapabilityPage";
import { EvidencePage } from "@/pages/EvidencePage";
import { LoginPage } from "@/pages/LoginPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { ProfilesPage } from "@/pages/ProfilesPage";
import { PromptPage } from "@/pages/PromptPage";
import { RunPage } from "@/pages/RunPage";
import { RunsPage } from "@/pages/RunsPage";
import { SecretsPage } from "@/pages/SecretsPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2_000, refetchOnWindowFocus: false } },
});

function RequireToken(): ReactElement {
  if (!getToken()) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <Outlet />;
}

export function App(): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireToken />}>
            <Route element={<Layout />}>
              <Route index element={<PromptPage />} />
              <Route path="runs" element={<RunsPage />} />
              <Route path="runs/:id" element={<RunPage />} />
              <Route path="capabilities" element={<CapabilitiesPage />} />
              <Route path="capabilities/:id" element={<CapabilityPage />} />
              <Route path="profiles" element={<ProfilesPage />} />
              <Route path="profiles/:id" element={<ProfilePage />} />
              <Route path="secrets" element={<SecretsPage />} />
              <Route path="evidence/:runId" element={<EvidencePage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
