// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Page hero — eyebrow + title + subtitle, with an optional right-side
 * action slot. Renders inside an AppShell.
 */
type PageHeaderProps = {
  title:     ReactNode;
  subtitle?: ReactNode;
  eyebrow?:  ReactNode;
  actions?:  ReactNode;
  className?: string;
};

export function PageHeader({
  title,
  subtitle,
  eyebrow,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <section className={cn("pt-12 pb-7 fade-in-up", className)}>
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          {eyebrow && (
            <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-brand-700/80 mb-2">
              {eyebrow}
            </p>
          )}
          <h1 className="text-[36px] sm:text-[42px] font-semibold tracking-tight text-zinc-900 leading-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-3 text-[17px] text-zinc-600 max-w-2xl leading-relaxed whitespace-pre-line">
              {subtitle}
            </p>
          )}
        </div>
        {actions && <div className="shrink-0 flex items-center gap-2">{actions}</div>}
      </div>
    </section>
  );
}