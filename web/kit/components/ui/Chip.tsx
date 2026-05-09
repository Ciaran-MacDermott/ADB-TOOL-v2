// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

export type ChipTone = "neutral" | "info" | "success" | "warning" | "error";

const toneClass: Record<ChipTone, string> = {
  neutral: "bg-zinc-100    text-zinc-700",
  info:    "bg-brand-50    text-brand-700",
  success: "bg-emerald-50  text-emerald-700",
  warning: "bg-amber-50    text-amber-800",
  error:   "bg-red-50      text-red-700",
};

const dotClass: Record<ChipTone, string> = {
  neutral: "bg-zinc-400",
  info:    "bg-brand-600",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error:   "bg-red-500",
};

type ChipProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: ChipTone;
  dot?: boolean;
  children: ReactNode;
};

export function Chip({
  tone = "neutral",
  dot = true,
  className,
  children,
  ...rest
}: ChipProps) {
  return (
    <span className={cn("chip", toneClass[tone], className)} {...rest}>
      {dot && <span className={cn("chip-dot", dotClass[tone])} />}
      {children}
    </span>
  );
}