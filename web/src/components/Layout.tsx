import { useState, type ReactElement } from "react";

import {
  Boxes,
  KeyRound,
  ListChecks,
  LogOut,
  PanelLeft,
  SlidersHorizontal,
  Sparkles,
  Zap,
} from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { ThemeToggle } from "@/components/ThemeToggle";
import { useHealth } from "@/api/queries";
import { clearToken } from "@/lib/auth";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  icon: typeof Sparkles;
  end?: boolean;
};

const NAV: NavItem[] = [
  { to: "/", label: "Prompt", icon: Sparkles, end: true },
  { to: "/runs", label: "Runs", icon: ListChecks },
  { to: "/capabilities", label: "Capabilities", icon: Boxes },
  { to: "/profiles", label: "Profiles", icon: SlidersHorizontal },
  { to: "/secrets", label: "Secrets", icon: KeyRound },
];

const SIDEBAR_KEY = "operant.sidebar.collapsed";

function initialCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

function HealthDot(): ReactElement {
  const health = useHealth();
  const ok = health.data?.ok === true;
  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground sm:flex"
      title={health.error ? "Backend unreachable" : `Backend ${health.data?.version ?? ""}`}
    >
      <span
        className={cn(
          "inline-block size-2 rounded-full",
          ok ? "bg-success" : health.isPending ? "bg-muted-foreground/50" : "bg-destructive",
        )}
      />
      {ok ? `v${health.data?.version ?? ""}` : health.isPending ? "connecting" : "offline"}
    </span>
  );
}

function signOut(): void {
  clearToken();
  window.location.assign("/login");
}

export function Layout(): ReactElement {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const toggle = (): void => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  };

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-card/80 px-3 backdrop-blur">
        <button
          type="button"
          onClick={toggle}
          aria-label="Toggle sidebar"
          className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <PanelLeft className="size-4" />
        </button>
        <div className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Zap className="size-4" />
          </span>
          <span className="text-base font-semibold tracking-tight">Operant</span>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <HealthDot />
          <ThemeToggle />
          <button
            type="button"
            onClick={signOut}
            title="Sign out"
            aria-label="Sign out"
            className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        <aside
          className={cn(
            "sticky top-14 z-20 flex h-[calc(100vh-3.5rem)] shrink-0 flex-col gap-1 border-r border-border bg-sidebar p-2 transition-[width] duration-200",
            collapsed ? "w-16" : "w-60",
          )}
        >
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              title={collapsed ? n.label : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  collapsed && "justify-center px-0",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-sidebar-foreground/80 hover:bg-accent hover:text-accent-foreground",
                )
              }
            >
              <n.icon className="size-4 shrink-0" />
              {!collapsed && <span className="truncate">{n.label}</span>}
            </NavLink>
          ))}
        </aside>

        <main className="min-w-0 flex-1">
          <div className="w-full px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
