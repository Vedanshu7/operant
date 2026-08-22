import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { getToken, setToken } from "@/lib/auth";
import { initTheme } from "@/lib/theme";

import "@/index.css";

initTheme();

async function enableMocks(): Promise<void> {
  if (import.meta.env.VITE_USE_MOCKS !== "1") return;
  const { worker } = await import("@/mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
  if (!getToken()) setToken("mock-token");
}

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");

void enableMocks().then(() => {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
