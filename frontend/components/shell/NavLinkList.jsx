"use client";

/**
 * NavLinkList — the plain-link rendering of one nav group's items, with
 * the group's section headings, for the surfaces that are NOT a dropdown
 * menu: the mobile menu drawer and the /more site map.
 *
 * The desktop dropdown (NavMenu) renders the same `sectionRuns` with menu
 * semantics.  Before this, only the desktop dropdown showed section
 * headings — the drawer and /more flattened them away — so a phone user
 * saw "Waivers", "Waiver Advisor" and "Weekly IDP Streaming" as three
 * unrelated rows while a desktop user saw them grouped (UX audit
 * 2026-11-01, NAV-05).  One helper, both surfaces, so they cannot drift.
 */
import Link from "next/link";
import { useId } from "react";
import { isNavActive, sectionRuns } from "@/lib/nav-model";

export default function NavLinkList({ items, pathname = null, onNavigate }) {
  const baseId = useId();

  const renderItem = (item) => (
    <Link
      key={item.href}
      href={item.href}
      className="shell-menu-item"
      aria-current={pathname && isNavActive(item.href, pathname) ? "page" : undefined}
      onClick={onNavigate}
    >
      <span>{item.label}</span>
      {item.hint ? <span className="shell-menu-item-hint">{item.hint}</span> : null}
    </Link>
  );

  return (
    <div className="shell-drawer-list">
      {sectionRuns(items).map((run, i) => {
        if (!run.section) return run.items.map(renderItem);
        const headingId = `${baseId}-sec-${i}`;
        return (
          <div
            key={`sec-${run.section}-${i}`}
            role="group"
            aria-labelledby={headingId}
            className="shell-menu-group"
          >
            <p id={headingId} className="shell-menu-section">
              {run.section}
            </p>
            {run.items.map(renderItem)}
          </div>
        );
      })}
    </div>
  );
}
