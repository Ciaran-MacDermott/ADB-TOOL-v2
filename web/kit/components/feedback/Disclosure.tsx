// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export type DisclosureTone = "neutral" | "info" | "success" | "warning" | "error";

const dotClass: Record<DisclosureTone, string> = {
  neutral: "bg-zinc-400",
  info:    "bg-brand-600",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error:   "bg-red-500",
};

/**
 * Native <details>/<summary> with a colored status dot in the summary
 * row. Use for collapsible debug panels, advanced settings, or per-item
 * detail rows in lists. Stays uncontrolled (browser handles open/close);
 * pass `defaultOpen` to start expanded.
 */
type DisclosureProps = {
  summary: ReactNode;
  /** Optional dot color. Omit to skip the dot entirely. */
  tone?: DisclosureTone;
  defaultOpen?: boolean;
  className?: string;
  children: ReactNode;
};

export function Disclosure({
  summary,
  tone,
  defaultOpen,
  className,
  children,
}: DisclosureProps) {
  return (
    <details className={cn("disclosure", className)} open={defaultOpen}>
      <summary>
        {tone && <span className={cn("h-2 w-2 rounded-full", dotClass[tone])} />}
        <span className="flex-1">{summary}</span>
        <span className="text-xs text-zinc-400">▾</span>
      </summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}