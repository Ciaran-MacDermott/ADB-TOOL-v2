// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { InputHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label?: ReactNode;
};

export function Checkbox({ label, className, id, ...rest }: CheckboxProps) {
  const input = (
    <input
      id={id}
      type="checkbox"
      className={cn(
        "h-4 w-4 rounded border-zinc-300 text-brand-700",
        "focus:ring-2 focus:ring-brand-500/30 focus:ring-offset-0",
        "disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...rest}
    />
  );

  if (!label) return input;

  return (
    <label
      htmlFor={id}
      className="inline-flex items-center gap-2 text-sm text-zinc-700 cursor-pointer select-none"
    >
      {input}
      <span>{label}</span>
    </label>
  );
}