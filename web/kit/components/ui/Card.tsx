// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type CardVariant = "glass" | "quiet";

type CardProps = HTMLAttributes<HTMLDivElement> & {
  variant?: CardVariant;
};

export function Card({ variant = "glass", className, ...rest }: CardProps) {
  const base = variant === "glass" ? "surface-card" : "surface-card-quiet";
  return <div className={cn(base, "p-5", className)} {...rest} />;
}

export function CardHeader({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-3 flex items-center justify-between gap-3", className)} {...rest} />;
}

export function CardTitle({ className, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-base font-semibold tracking-tight text-[color:var(--ink-1)]", className)}
      {...rest}
    />
  );
}

export function CardDescription({ className, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn("text-sm text-[color:var(--ink-3)] leading-relaxed", className)} {...rest} />
  );
}