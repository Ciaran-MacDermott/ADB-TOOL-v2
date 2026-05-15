// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * Primary nav strip for the AppBar's center slot. Stays
 * framework-agnostic: pass a `renderLink` callback so the consuming app
 * decides whether to use next/link, react-router, or plain <a>.
 *
 * Usage:
 *   <NavTabs
 *     items={[{ key: "home", label: "Home", href: "/" }, …]}
 *     activeKey="home"
 *     renderLink={({ href, className, children }) =>
 *       <Link href={href} className={className}>{children}</Link>}
 *   />
 */
export type NavItem = {
  key: string;
  label: ReactNode;
  href: string;
  disabled?: boolean;
};

type RenderLinkArgs = {
  href: string;
  className: string;
  children: ReactNode;
};

type NavTabsProps = {
  items: ReadonlyArray<NavItem>;
  activeKey: string;
  renderLink: (args: RenderLinkArgs) => ReactNode;
  className?: string;
};

export function NavTabs({ items, activeKey, renderLink, className }: NavTabsProps) {
  return (
    <nav className={cn("flex items-center gap-1", className)}>
      {items.map((item) => {
        const active = item.key === activeKey;
        const cls = cn(
          "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
          active
            ? "bg-brand-50 text-brand-700"
            : "text-zinc-600 hover:bg-zinc-100/70 hover:text-zinc-900",
          item.disabled && "opacity-50 pointer-events-none",
        );
        return (
          <span key={item.key}>
            {renderLink({
              href: item.href,
              className: cls,
              children: item.label,
            })}
          </span>
        );
      })}
    </nav>
  );
}