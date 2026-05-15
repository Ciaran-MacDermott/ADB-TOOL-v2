import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Wordmark for the AppBar's left slot: logo + slash + app tag.
 *
 * Framework-agnostic; if the consuming app uses next/link, wrap this in <Link href="/">.
 * Expects /Circana_logo.png to be served from the app's public/ folder.
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