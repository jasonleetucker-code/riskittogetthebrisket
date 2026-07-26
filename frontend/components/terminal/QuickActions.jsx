"use client";

import Link from "next/link";
import { Icon, Panel } from "@/components/ds";

const ACTIONS = [
  { href: "/finder", label: "Trade Finder" },
  { href: "/trade", label: "Trade Calculator" },
  { href: "/rankings", label: "Rankings" },
  { href: "/rosters", label: "Rosters" },
];

/**
 * Quick Actions — deep links into the rest of the app from the
 * landing page.  Structural stub: no icons, no counts.
 */
export default function QuickActions() {
  return (
    <Panel title="Quick actions">
      <ul className="quick-actions">
        {ACTIONS.map((a) => (
          <li key={a.href}>
            <Link href={a.href} className="quick-action">
              <span className="quick-action-label">{a.label}</span>
              <Icon name="chevron-right" size={14} aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
