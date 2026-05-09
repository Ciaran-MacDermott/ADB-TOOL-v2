// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

export type BadgeTone = "neutral" | "info" | "success" | "warning" | "error";

const toneClass: Record<BadgeTone, string> = {
  neutral: "bg-zinc-50    text-zinc-700    border-zinc-200    [--dot:#71717A]",
  info:    "bg-brand-50   text-brand-700   border-brand-200   [--dot:#4E106F]",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200 [--dot:#059669]",
  warning: "bg-amber-50   text-amber-800   border-amber-200   [--dot:#D97706]",
  error:   "bg-red-50     text-red-700     border-red-200     [--dot:#DC2626]",
};

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: BadgeTone;
  dot?: boolean;
  children: ReactNode;
};

export function Badge({
  tone = "neutral",
  dot = true,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border",
        toneClass[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-[var(--dot)]" />}
      {children}
    </span>
  );
}