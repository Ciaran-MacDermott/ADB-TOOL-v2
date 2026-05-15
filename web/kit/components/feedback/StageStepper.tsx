// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Multi-step indicator for wizard-style flows. Pass an ordered list of
 * step keys + the active index; renders dots+labels with the active and
 * completed steps highlighted in brand color.
 *
 * Stays controlled (no internal state) — caller owns where they are in
 * the flow. Click handler is optional for navigable steppers; omit it
 * for read-only progress display.
 */
export type StepperStep = {
  key: string;
  label: ReactNode;
  /** Optional sub-label shown smaller below. */
  caption?: ReactNode;
};

type StageStepperProps = {
  steps: ReadonlyArray<StepperStep>;
  /** Index of the active step (0-based). Steps before this index are "complete". */
  activeIndex: number;
  /** Optional click handler for step navigation. Receives index + key. */
  onStepClick?: (index: number, key: string) => void;
  className?: string;
};

export function StageStepper({
  steps,
  activeIndex,
  onStepClick,
  className,
}: StageStepperProps) {
  return (
    <ol className={cn("flex items-center gap-2 sm:gap-3", className)}>
      {steps.map((step, i) => {
        const status: "complete" | "active" | "upcoming" =
          i < activeIndex ? "complete" : i === activeIndex ? "active" : "upcoming";

        const dotClass =
          status === "complete" ? "bg-brand-600 text-white"
        : status === "active"   ? "bg-brand-700 text-white ring-4 ring-brand-200/60"
        :                         "bg-zinc-200 text-zinc-500";

        const labelClass =
          status === "upcoming" ? "text-zinc-500" : "text-zinc-900 font-medium";

        const dotContent = status === "complete" ? "✓" : i + 1;

        const inner = (
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                "h-7 w-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0",
                dotClass,
              )}
            >
              {dotContent}
            </span>
            <div className="min-w-0">
              <div className={cn("text-sm truncate", labelClass)}>{step.label}</div>
              {step.caption && (
                <div className="text-[11px] text-zinc-400 truncate">{step.caption}</div>
              )}
            </div>
          </div>
        );

        return (
          <li key={step.key} className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
            {onStepClick ? (
              <button
                type="button"
                onClick={() => onStepClick(i, step.key)}
                className="text-left min-w-0 outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 rounded-lg"
              >
                {inner}
              </button>
            ) : (
              inner
            )}
            {i < steps.length - 1 && (
              <span
                className={cn(
                  "flex-1 h-px",
                  i < activeIndex ? "bg-brand-300" : "bg-zinc-200",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}