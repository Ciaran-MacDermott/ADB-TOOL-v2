// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Field wraps any form control with a label, optional hint, and optional
 * error message. Pair with <Input>, <Select>, <Checkbox>, <Textarea>, or
 * a custom control — this primitive handles the chrome, the control owns
 * its own value/onChange.
 */
type FieldProps = {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Pass htmlFor to associate the label with a control by id. */
  htmlFor?: string;
  /** Visually hide the label but keep it for screen readers. */
  hideLabel?: boolean;
  className?: string;
  children: ReactNode;
};

export function Field({
  label,
  hint,
  error,
  htmlFor,
  hideLabel,
  className,
  children,
}: FieldProps) {
  return (
    <div className={cn("min-w-0", className)}>
      <label
        htmlFor={htmlFor}
        className={cn("field-label", hideLabel && "sr-only")}
      >
        {label}
      </label>
      {children}
      {hint && !error && <p className="field-hint">{hint}</p>}
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}