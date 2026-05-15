// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Segmented toggle pill — two or more mutually-exclusive options shown
 * as a single rounded control. Use for binary or small-set mode picks
 * (e.g. "Light / Dark", "Quarterly / Annual"). For 4+ options consider
 * a Select instead.
 */
export type SegmentOption<T extends string> = {
  value: T;
  label: ReactNode;
  disabled?: boolean;
};

type SegmentedControlProps<T extends string> = {
  options: ReadonlyArray<SegmentOption<T>>;
  value: T;
  onChange: (value: T) => void;
  /** Optional accessibility label for the group. */
  ariaLabel?: string;
  className?: string;
};

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center p-0.5 rounded-lg border bg-white",
        "border-[color:var(--hairline-strong)]",
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={opt.disabled}
            onClick={() => onChange(opt.value)}
            className={cn(
              "px-3 py-1 rounded-md text-xs font-medium transition-colors",
              active
                ? "bg-brand-700 text-white"
                : "text-zinc-600 hover:bg-zinc-100",
              opt.disabled && "opacity-50 cursor-not-allowed",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}