// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { SelectHTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

export type SelectOption<T extends string = string> = {
  value: T;
  label: ReactNode;
  disabled?: boolean;
};

type SelectProps<T extends string = string> = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "children"
> & {
  options: ReadonlyArray<SelectOption<T>>;
  invalid?: boolean;
  /** Optional placeholder rendered as a disabled, value="" first option. */
  placeholder?: string;
};

export function Select<T extends string = string>({
  options,
  invalid,
  placeholder,
  className,
  ...rest
}: SelectProps<T>) {
  return (
    <select
      className={cn(
        "input-base appearance-none pr-9 bg-no-repeat bg-[right_0.6rem_center] bg-[length:1rem]",
        // Tiny SVG chevron — keeps Select from depending on an icon library.
        "bg-[url('data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2020%2020%22%20fill%3D%22%2364748B%22%3E%3Cpath%20fill-rule%3D%22evenodd%22%20d%3D%22M5.23%207.21a.75.75%200%20011.06.02L10%2011.06l3.71-3.83a.75.75%200%20111.08%201.04l-4.25%204.39a.75.75%200%2001-1.08%200L5.21%208.27a.75.75%200%2001.02-1.06z%22%20clip-rule%3D%22evenodd%22%2F%3E%3C%2Fsvg%3E')]",
        invalid && "input-error",
        className,
      )}
      {...rest}
    >
      {placeholder !== undefined && (
        <option value="" disabled>
          {placeholder}
        </option>
      )}
      {options.map((opt) => (
        <option key={opt.value} value={opt.value} disabled={opt.disabled}>
          {opt.label as string}
        </option>
      ))}
    </select>
  );
}