"use client";

import Link from "next/link";
import { Icon, Panel } from "@/components/ds";

// Labels here are the canonical names from lib/nav-model.js.  This
// panel used to label /finder "Trade Finder" — a name that belonged to
// a different page (/angle) — so the one navigational shortcut on the
// dashboard pointed at the wrong tool.
export const QUICK_ACTIONS = [
  // Game Day first: "how is my matchup going" is the in-season question
  // a manager opens the dashboard with, and it was the one weekly
  // destination with no shortcut here (UX audit 2026-11-01, NAV-06).
  { href: "/game-day", label: "Game Day" },
  { href: "/rankings", label: "Rankings" },
  { href: "/trade", label: "Trade Calculator" },
  { href: "/waivers", label: "Waivers" },
  { href: "/rosters", label: "Team Strength" },
];

/**
 * Quick Actions — deep links into the rest of the app from the
 * dashboard.  Five everyday destinations, in the order a manager
 * usually wants them: this week's matchup, check values, price a deal,
 * work the wire, look at the field.
 */
export default function QuickActions() {
  return (
    <Panel className="panel--actions" title="Quick actions">
      <ul className="quick-actions">
        {QUICK_ACTIONS.map((a) => (
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
