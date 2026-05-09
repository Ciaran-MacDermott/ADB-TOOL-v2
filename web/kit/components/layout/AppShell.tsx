// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Page-level wrapper. Sits inside <body>, gives every route the same
 * max-width gutter + vertical rhythm, and lets pages opt out per-section
 * by rendering a full-bleed child outside <AppShell>.
 */
type AppShellProps = {
  children: ReactNode;
  className?: string;
  /** Override the standard 5xl content width when a page needs more room. */
  maxWidth?: "5xl" | "6xl" | "7xl" | "full";
};

const widthClass = {
  "5xl":  "max-w-5xl",
  "6xl":  "max-w-6xl",
  "7xl":  "max-w-7xl",
  "full": "max-w-none",
} as const;

export function AppShell({ children, className, maxWidth = "5xl" }: AppShellProps) {
  return (
    <div className={cn("mx-auto px-6 pb-16", widthClass[maxWidth], className)}>
      {children}
    </div>
  );
}