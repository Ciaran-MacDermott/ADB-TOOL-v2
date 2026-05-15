// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Empty / "nothing here yet" state. Use inside a panel or directly under
 * a PageHeader when the page has no data. Optional action slot for the
 * one CTA that would unblock the user.
 */
type EmptyStateProps = {
  title: ReactNode;
  body?: ReactNode;
  /** Optional icon node — keep small (24-32px). Kit stays icon-library-agnostic. */
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ title, body, icon, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "surface-card-quiet text-center px-6 py-12 flex flex-col items-center gap-3",
        className,
      )}
    >
      {icon && <div className="text-zinc-400">{icon}</div>}
      <h3 className="text-base font-semibold text-zinc-900">{title}</h3>
      {body && (
        <p className="text-sm text-zinc-500 max-w-md leading-relaxed">{body}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}