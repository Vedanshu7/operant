import { storageGet, storageSet } from "@/lib/safeStorage";

export type Theme = "light" | "dark";

const KEY = "operant.theme";

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getTheme(): Theme {
  const stored = storageGet(KEY);
  if (stored === "light" || stored === "dark") return stored;
  return systemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function setTheme(theme: Theme): void {
  storageSet(KEY, theme);
  applyTheme(theme);
}

export function initTheme(): void {
  applyTheme(getTheme());
}
