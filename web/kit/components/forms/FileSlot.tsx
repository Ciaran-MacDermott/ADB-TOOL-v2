// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
"use client";

import { useRef, useState, type ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Drag-and-drop + click-to-browse file picker. Single file by default;
 * pass `multiple` for multi-file. Calls `onSelect` with the chosen
 * File[]; stays uncontrolled internally beyond visual drag state.
 *
 * Validates extensions client-side via `accept` (comma-separated, e.g.
 * ".xlsx,.csv"). Invalid drops are rejected with `onReject`.
 */
type FileSlotProps = {
  onSelect: (files: File[]) => void;
  /** Comma-separated extensions, e.g. ".xlsx,.csv". */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  label?: ReactNode;
  hint?: ReactNode;
  /** Called when a file fails the accept filter. */
  onReject?: (files: File[], reason: string) => void;
  className?: string;
};

export function FileSlot({
  onSelect,
  accept,
  multiple,
  disabled,
  label = "Drop a file here",
  hint,
  onReject,
  className,
}: FileSlotProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  function filter(files: File[]): File[] {
    if (!accept) return files;
    const exts = accept
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    const ok: File[] = [];
    const bad: File[] = [];
    for (const f of files) {
      const name = f.name.toLowerCase();
      if (exts.some((ext) => name.endsWith(ext))) ok.push(f);
      else bad.push(f);
    }
    if (bad.length && onReject) {
      onReject(bad, `Expected ${exts.join(" or ")}`);
    }
    return ok;
  }

  function emit(files: FileList | null) {
    if (!files || files.length === 0) return;
    const arr = filter(Array.from(files));
    if (arr.length === 0) return;
    onSelect(multiple ? arr : [arr[0]]);
  }

  return (
    <div
      onDragOver={(e) => {
        if (disabled) return;
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        if (disabled) return;
        e.preventDefault();
        setDrag(false);
        emit(e.dataTransfer.files);
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      className={cn(
        "rounded-xl border-2 border-dashed bg-white/50 px-6 py-8",
        "flex flex-col items-center justify-center gap-2 text-center cursor-pointer",
        "transition-colors duration-150",
        drag
          ? "border-brand-500 bg-brand-50/60"
          : "border-zinc-300 hover:border-brand-400 hover:bg-zinc-50/70",
        disabled && "opacity-60 cursor-not-allowed pointer-events-none",
        className,
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="sr-only"
        onChange={(e) => emit(e.target.files)}
      />
      <p className="text-sm font-medium text-zinc-700">{label}</p>
      {hint && <p className="text-xs text-zinc-500">{hint}</p>}
      <p className="text-xs text-zinc-400">
        or <span className="text-brand-700 font-medium">browse</span>
      </p>
    </div>
  );
}