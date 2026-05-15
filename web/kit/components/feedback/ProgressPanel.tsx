// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { Card } from "../ui/Card";
import { Badge, type BadgeTone } from "../ui/Badge";
import { ProgressBar } from "./ProgressBar";
import { Spinner } from "../ui/Spinner";
import { cn } from "../../lib/cn";

/**
 * Status panel for long-running async work — title + state badge + progress
 * bar + optional metadata (queue position, elapsed, etc) + optional log
 * tail or detail slot. Pair with a polling hook (see usePolling).
 */
export type ProgressState =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

const STATE_TONE: Record<ProgressState, BadgeTone> = {
  queued:    "neutral",
  running:   "info",
  succeeded: "success",
  failed:    "error",
  cancelled: "neutral",
};

const STATE_LABEL: Record<ProgressState, string> = {
  queued:    "Queued",
  running:   "Running",
  succeeded: "Succeeded",
  failed:    "Failed",
  cancelled: "Cancelled",
};

type ProgressPanelProps = {
  title: ReactNode;
  state: ProgressState;
  /** 0–100. When omitted while running, shows indeterminate animation. */
  percent?: number;
  /** Sub-line under the title, e.g. "Stage 2 of 4 — Generating slides". */
  subline?: ReactNode;
  /** Right-aligned metadata strip — e.g. queue position, elapsed time. */
  meta?: ReactNode;
  /** Optional content under the bar (e.g. <LogTail /> or <Disclosure>). */
  children?: ReactNode;
  className?: string;
};

export function ProgressPanel({
  title,
  state,
  percent,
  subline,
  meta,
  children,
  className,
}: ProgressPanelProps) {
  const tone = STATE_TONE[state];
  const showSpinner = state === "running" || state === "queued";

  return (
    <Card className={cn("space-y-3", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {showSpinner && <Spinner size={14} className="text-brand-600" />}
            <h3 className="text-base font-semibold text-zinc-900 truncate">{title}</h3>
            <Badge tone={tone}>{STATE_LABEL[state]}</Badge>
          </div>
          {subline && (
            <p className="mt-1 text-sm text-zinc-500 leading-relaxed">{subline}</p>
          )}
        </div>
        {meta && (
          <div className="shrink-0 text-xs text-zinc-500 tabular-nums text-right">
            {meta}
          </div>
        )}
      </div>

      {(state === "running" || state === "queued" || percent !== undefined) && (
        <ProgressBar
          indeterminate={showSpinner && percent === undefined}
          value={percent}
          tone={
            state === "failed"    ? "error"
          : state === "succeeded" ? "success"
          : "brand"
          }
        />
      )}

      {children}
    </Card>
  );
}