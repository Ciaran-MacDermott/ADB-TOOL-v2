// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Slim sticky app bar. Three slots:
 *   - left:    wordmark / logo (caller decides whether to wrap in <Link>)
 *   - center:  primary nav (optional)
 *   - right:   actions (optional)
 *
 * Stays framework-agnostic — does not import next/link so it can be used
 * in any React app. Callers wrap children in their own routing primitive.
 */
type AppBarProps = {
  left:    ReactNode;
  center?: ReactNode;
  right?:  ReactNode;
  className?: string;
  /** Match the inner gutter to your AppShell's maxWidth. */
  maxWidth?: "5xl" | "6xl" | "7xl" | "full";
};

const widthClass = {
  "5xl":  "max-w-5xl",
  "6xl":  "max-w-6xl",
  "7xl":  "max-w-7xl",
  "full": "max-w-none",
} as const;

export function AppBar({
  left,
  center,
  right,
  className,
  maxWidth = "5xl",
}: AppBarProps) {
  return (
    <header className={cn("app-bar", className)}>
      <div className={cn("mx-auto px-6 h-[70px] flex items-center justify-between gap-4", widthClass[maxWidth])}>
        <div className="flex items-center gap-6">
          {left}
          {center && <div className="hidden md:flex">{center}</div>}
        </div>
        {right && <div className="flex items-center gap-2">{right}</div>}
      </div>
    </header>
  );
}