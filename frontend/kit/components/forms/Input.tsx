import type { InputHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
};

export function Input({ invalid, className, ...rest }: InputProps) {
  return (
    <input
      className={cn("input-base", invalid && "input-error", className)}
      {...rest}
    />
  );
}