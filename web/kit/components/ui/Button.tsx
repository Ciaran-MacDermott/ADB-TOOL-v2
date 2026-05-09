// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export type ButtonVariant =
  | "primary"
  | "success"
  | "secondary"
  | "ghost"
  | "danger-outline";

const variantClass: Record<ButtonVariant, string> = {
  primary:          "btn-primary",
  success:          "btn-success",
  secondary:        "btn-secondary",
  ghost:            "btn-ghost",
  "danger-outline": "btn-danger-outline",
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

export function Button({ variant = "primary", className, ...rest }: ButtonProps) {
  return <button className={cn(variantClass[variant], className)} {...rest} />;
}

type ButtonLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant?: ButtonVariant;
};

export function ButtonLink({ variant = "primary", className, ...rest }: ButtonLinkProps) {
  return <a className={cn(variantClass[variant], "no-underline", className)} {...rest} />;
}