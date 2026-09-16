import { storageGet, storageRemove, storageSet } from "@/lib/safeStorage";

export const TOKEN_KEY = "operant.token";

export function getToken(): string | null {
  return storageGet(TOKEN_KEY);
}

export function setToken(token: string): void {
  storageSet(TOKEN_KEY, token);
}

export function clearToken(): void {
  storageRemove(TOKEN_KEY);
}

export function redirectToLogin(): void {
  if (window.location.pathname === "/login") return;
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.assign(`/login?next=${next}`);
}
