// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Horizontal label/value pair. Use inside cards or panels for read-only
 * metadata strips (e.g. "Run id: abc123 — Started: 2 mins ago").
 *
 * For editable form fields use <Field> instead.
 */
type RowProps = {
  label: ReactNode;
  value?: ReactNode;
  /** Optional alignment; defaults to "between" (label left, value right). */
  align?: "between" | "start";
  className?: string;
  children?: ReactNode;
};

export function Row({ label, value, align = "between", className, children }: RowProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 text-sm",
        align === "between" ? "justify-between" : "justify-start",
        className,
      )}
    >
      <span className="text-zinc-500">{label}</span>
      <span className="text-zinc-800 font-medium tabular-nums">
        {value ?? children}
      </span>
    </div>
  );
}