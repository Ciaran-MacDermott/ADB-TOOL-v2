// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { AppBar } from "./AppBar";
import { Wordmark } from "./Wordmark";
import { PageHeader } from "./PageHeader";

/**
 * Convenience composition of AppBar + Wordmark + PageHeader. Most apps
 * render this exact stack at the top of their root page; rather than
 * each app re-composing it, render <AppHeader> and pass slots.
 *
 * If you need to break this up (nav in the AppBar, custom hero layout),
 * drop to the individual primitives instead.
 */
type AppHeaderProps = {
  /** Short app name shown after the Circana wordmark slash. */
  tag: ReactNode;
  /** Page title shown in the hero. */
  title: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  /** Optional right-side AppBar slot — buttons, status, profile menu. */
  appBarRight?: ReactNode;
  /** Optional AppBar center slot — typically <NavTabs />. */
  appBarCenter?: ReactNode;
  /** Optional PageHeader action slot — typically a primary CTA Button. */
  headerActions?: ReactNode;
  /** Wrap the wordmark in your routing primitive (e.g. next/link Link). */
  wordmarkLink?: (children: ReactNode) => ReactNode;
};

export function AppHeader({
  tag,
  title,
  subtitle,
  eyebrow,
  appBarRight,
  appBarCenter,
  headerActions,
  wordmarkLink,
}: AppHeaderProps) {
  const mark = <Wordmark tag={tag} />;
  return (
    <>
      <AppBar
        left={wordmarkLink ? wordmarkLink(mark) : mark}
        center={appBarCenter}
        right={appBarRight}
      />
      <PageHeader
        title={title}
        subtitle={subtitle}
        eyebrow={eyebrow}
        actions={headerActions}
      />
    </>
  );
}