// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import { cn } from "../../lib/cn";

type SpinnerProps = {
  /** Pixel size of the spinner. Defaults to 16. */
  size?: number;
  /** Override stroke color. Defaults to current text color. */
  className?: string;
  /** Accessibility label. Renders as visually-hidden text. */
  label?: string;
};

/**
 * Tiny CSS-only spinner — borderless dependency, inherits text color via
 * border-current. Use inline next to status text or as a Button child.
 */
export function Spinner({ size = 16, className, label }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "inline-block rounded-full border-[2px] border-current border-t-transparent",
        "animate-spin align-[-2px]",
        className,
      )}
      style={{ width: size, height: size }}
    >
      {label && <span className="sr-only">{label}</span>}
    </span>
  );
}