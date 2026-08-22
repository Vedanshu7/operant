import { useState, type ReactElement } from "react";

import { Moon, Sun } from "lucide-react";

import { getTheme, setTheme, type Theme } from "@/lib/theme";

export function ThemeToggle(): ReactElement {
  const [theme, setThemeState] = useState<Theme>(getTheme);
  const toggle = (): void => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle theme"
      title={theme === "dark" ? "Switch to light" : "Switch to dark"}
      className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}
