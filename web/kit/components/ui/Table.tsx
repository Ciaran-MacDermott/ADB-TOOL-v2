// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Light wrapper around <table> for the "render some rows" 80% case. For
 * editable spreadsheets or 10K+ rows reach for AG Grid (AIC pattern) —
 * this primitive is for read-only previews, lookup tables, and small
 * data displays.
 *
 * Usage:
 *   <Table
 *     columns={[
 *       { key: "name",  header: "Name" },
 *       { key: "value", header: "Value", align: "right" },
 *     ]}
 *     rows={data}
 *   />
 */
export type TableColumn<R> = {
  key: keyof R & string;
  header: ReactNode;
  align?: "left" | "right" | "center";
  /** Custom cell renderer. Receives the row and the raw value. */
  render?: (row: R, value: R[keyof R]) => ReactNode;
  className?: string;
};

type TableProps<R> = {
  columns: ReadonlyArray<TableColumn<R>>;
  rows: ReadonlyArray<R>;
  /** Optional key extractor; falls back to row index. */
  rowKey?: (row: R, index: number) => string | number;
  /** Optional message when rows is empty. */
  empty?: ReactNode;
  className?: string;
};

const alignClass = {
  left:   "text-left",
  right:  "text-right",
  center: "text-center",
};

export function Table<R extends Record<string, unknown>>({
  columns,
  rows,
  rowKey,
  empty = "No rows",
  className,
}: TableProps<R>) {
  return (
    <div
      className={cn(
        "overflow-x-auto rounded-xl border bg-white",
        "border-[color:var(--hairline)]",
        className,
      )}
    >
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-[color:var(--hairline)] bg-zinc-50/60">
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-500",
                  alignClass[c.align ?? "left"],
                  c.className,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-sm text-zinc-500"
              >
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={rowKey ? rowKey(row, i) : i}
                className="border-b border-[color:var(--hairline)] last:border-b-0 hover:bg-zinc-50/40"
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn("px-3 py-2 text-zinc-800", alignClass[c.align ?? "left"], c.className)}
                  >
                    {c.render
                      ? c.render(row, row[c.key as keyof R])
                      : (row[c.key as keyof R] as ReactNode)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}