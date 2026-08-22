import type { ButtonHTMLAttributes, ReactNode, ReactElement } from "react";

import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  children: ReactNode;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90",
  secondary:
    "border border-input bg-card text-foreground shadow-xs hover:bg-accent hover:text-accent-foreground",
  danger: "bg-destructive text-destructive-foreground shadow-xs hover:bg-destructive/90",
  ghost: "text-foreground hover:bg-accent hover:text-accent-foreground",
};

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  type = "button",
  children,
  ...rest
}: ButtonProps): ReactElement {
  const sizing = size === "sm" ? "h-8 gap-1.5 px-3 text-xs" : "h-9 gap-2 px-4 text-sm";
  return (
    <button
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
        VARIANTS[variant],
        sizing,
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
