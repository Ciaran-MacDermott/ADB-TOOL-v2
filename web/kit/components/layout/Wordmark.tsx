// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Circana wordmark for the AppBar's left slot.
 *
 * Pattern: logo + slash + app tag — same shape across every Circana app
 * so the brand chrome reads as a family. Stays framework-agnostic; if
 * the consuming app uses next/link, wrap this in <Link href="/">.
 *
 * Expects /Circana_logo.png to be served from the app's public/ folder.
 * kit/sync.sh installs it on every sync so apps don't have to manage
 * the asset themselves.
 */
type WordmarkProps = {
  /** Short app name shown after the slash, e.g. "Deck Builder", "Assortment AIC". */
  tag?: ReactNode;
  /** Override the default /Circana_logo.png path if needed. */
  src?: string;
  /** Override the alt text. */
  alt?: string;
  className?: string;
};

export function Wordmark({
  tag,
  src = "/Circana_logo.png",
  alt = "Circana",
  className,
}: WordmarkProps) {
  return (
    <span className={cn("flex items-center gap-3 group select-none", className)}>
      <img
        src={src}
        alt={alt}
        className="h-9 w-auto"
        draggable={false}
      />
      {tag && (
        <span className="hidden sm:flex items-baseline gap-1.5 text-[19px] font-semibold tracking-tight">
          <span className="text-zinc-300">/</span>
          <span className="text-brand-700">{tag}</span>
        </span>
      )}
    </span>
  );
}