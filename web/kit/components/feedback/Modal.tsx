// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
"use client";

import { useEffect, type ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Simple controlled modal. Locks body scroll when open and closes on
 * backdrop click + Escape key. Renders inline (no portal) — for the
 * vast majority of internal-tool use cases the parent stacking context
 * is fine. If a tool needs portal-rendering, swap to createPortal at
 * the call site.
 */
type ModalProps = {
  open: boolean;
  onClose: () => void;
  /** Optional heading shown in a card-style header. */
  title?: ReactNode;
  /** Optional footer slot for actions (typically Button[]). */
  footer?: ReactNode;
  /** Disable the backdrop-click-to-close affordance. */
  dismissOnBackdrop?: boolean;
  className?: string;
  children: ReactNode;
};

export function Modal({
  open,
  onClose,
  title,
  footer,
  dismissOnBackdrop = true,
  className,
  children,
}: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="overlay-backdrop"
      onClick={dismissOnBackdrop ? onClose : undefined}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={cn("overlay-panel", className)}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="px-5 py-4 border-b border-[color:var(--hairline)] flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="text-zinc-400 hover:text-zinc-700 text-lg leading-none px-1"
            >
              ✕
            </button>
          </div>
        )}
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="px-5 py-3 border-t border-[color:var(--hairline)] bg-zinc-50/60 flex items-center justify-end gap-2">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}