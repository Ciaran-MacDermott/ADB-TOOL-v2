// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import { cn } from "../../lib/cn";

/**
 * Determinate progress bar — pass a percentage 0-100. For indeterminate
 * progress (job is running but no known total) pass `indeterminate`.
 */
type ProgressBarProps = {
  value?: number;
  indeterminate?: boolean;
  /** Tailwind color shorthand for the fill — defaults to brand. */
  tone?: "brand" | "success" | "warning" | "error";
  className?: string;
};

const toneClass = {
  brand:   "bg-brand-600",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error:   "bg-red-500",
};

export function ProgressBar({
  value,
  indeterminate,
  tone = "brand",
  className,
}: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div
      className={cn(
        "h-2 w-full rounded-full bg-zinc-100 overflow-hidden relative",
        className,
      )}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : pct}
    >
      {indeterminate ? (
        <div
          className={cn(
            "absolute inset-y-0 w-1/3 rounded-full",
            toneClass[tone],
            "animate-[cui-indeterm_1.4s_cubic-bezier(0.22,1,0.36,1)_infinite]",
          )}
        />
      ) : (
        <div
          className={cn("h-full rounded-full transition-all duration-300", toneClass[tone])}
          style={{ width: `${pct}%` }}
        />
      )}
      <style>{`
        @keyframes cui-indeterm {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(300%); }
        }
      `}</style>
    </div>
  );
}