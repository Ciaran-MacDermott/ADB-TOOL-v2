// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
"use client";

import { useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import { Button } from "../ui/Button";
import { Badge, type BadgeTone } from "../ui/Badge";
import { cn } from "../../lib/cn";

/**
 * Categorised error dialog that consumes the canonical BFF error envelope:
 *
 *   {
 *     "error_title":    "Could not parse upload",
 *     "error_advice":   "Re-export the file as .xlsx and retry.",
 *     "error_category": "input" | "config" | "server",
 *     "error_detail"?:  "raw stack trace…",
 *   }
 *
 * Pair with FastAPI exception handlers that emit this shape uniformly —
 * the user sees a friendly title + advice; engineers can expand the
 * collapsible "Technical detail" section to copy the underlying trace.
 */

export type ErrorCategory = "input" | "config" | "server";

export type RunErrorEnvelope = {
  error_title?: string | null;
  error_advice?: string | null;
  error_category?: ErrorCategory | null;
  error_detail?: string | null;
};

const CATEGORY_LABEL: Record<ErrorCategory, string> = {
  input:  "Input problem",
  config: "Configuration issue",
  server: "Server error",
};

const CATEGORY_TONE: Record<ErrorCategory, BadgeTone> = {
  input:  "warning",
  config: "info",
  server: "error",
};

type RunErrorDialogProps = {
  open: boolean;
  onClose: () => void;
  error: RunErrorEnvelope | string | null;
  /** Optional retry handler — renders a "Try again" button when provided. */
  onRetry?: () => void;
  /** Override the default title when no envelope is provided. */
  fallbackTitle?: string;
};

export function RunErrorDialog({
  open,
  onClose,
  error,
  onRetry,
  fallbackTitle = "Something went wrong",
}: RunErrorDialogProps) {
  const [showDetail, setShowDetail] = useState(false);

  if (!error) return null;

  const env: RunErrorEnvelope =
    typeof error === "string"
      ? { error_title: fallbackTitle, error_advice: error }
      : error;

  const title    = env.error_title ?? fallbackTitle;
  const advice   = env.error_advice ?? undefined;
  const category = env.error_category ?? undefined;
  const detail   = env.error_detail ?? undefined;

  const footer: ReactNode = (
    <>
      {detail && (
        <Button
          variant="ghost"
          onClick={() => setShowDetail((v) => !v)}
          className="mr-auto"
        >
          {showDetail ? "Hide technical detail" : "Show technical detail"}
        </Button>
      )}
      <Button variant="secondary" onClick={onClose}>
        Dismiss
      </Button>
      {onRetry && (
        <Button variant="primary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </>
  );

  return (
    <Modal open={open} onClose={onClose} title={title} footer={footer}>
      <div className="space-y-3">
        {category && (
          <Badge tone={CATEGORY_TONE[category]}>{CATEGORY_LABEL[category]}</Badge>
        )}
        {advice && (
          <p className="text-sm text-zinc-700 leading-relaxed">{advice}</p>
        )}
        {detail && showDetail && (
          <pre
            className={cn(
              "mt-2 max-h-64 overflow-auto rounded-lg bg-zinc-900",
              "p-3 text-[11px] leading-relaxed text-zinc-100 font-mono whitespace-pre-wrap",
            )}
          >
            {detail}
          </pre>
        )}
      </div>
    </Modal>
  );
}