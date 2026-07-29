"use client";

import Link from "next/link";
import { Icon, Panel } from "@/components/ds";

// Labels here are the canonical names from lib/nav-model.js.  This
// panel used to label /finder "Trade Finder" — a name that belonged to
// a different page (/angle) — so the one navigational shortcut on the
// dashboard pointed at the wrong tool.
const ACTIONS = [
  { href: "/rankings", label: "Rankings" },
  { href: "/trade", label: "Trade Calculator" },
  { href: "/waivers", label: "Waivers" },
  { href: "/rosters", label: "Team Strength" },
];

/**
 * Quick Actions — deep links into the rest of the app from the
 * dashboard.  Four everyday destinations, in the order a manager
 * usually wants them: check values, price a deal, work the wire, look
 * at the field.
 */
export default function QuickActions() {
  return (
    <Panel className="panel--actions" title="Quick actions">
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
