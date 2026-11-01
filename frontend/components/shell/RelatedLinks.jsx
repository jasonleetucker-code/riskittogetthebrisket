"use client";

/**
 * RelatedLinks — a page's contextual "see also" row, resolved from the
 * ONE nav model.
 *
 * Not a second navigation system: it holds no labels, routes or gating
 * of its own.  `relatedNavItems` looks each href up in nav-model, so the
 * link text is the naming canon by construction, and a capability-gated
 * or admin-only destination is offered here exactly when the menus offer
 * it (fails closed while the auth probe is unresolved).  An href the
 * model does not know renders nothing.
 *
 * Why it exists (UX audit 2026-11-01, NAV-03/NAV-04): the waiver tools
 * were three menu rows with no way to move between them in context — a
 * user on /waivers had no sign that Weekly IDP Streaming existed — and
 * Sharp People had no inbound link a signed-in user could reach.
 */
import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";
import { relatedNavItems } from "@/lib/nav-model";

export default function RelatedLinks({ hrefs, label = "Related" }) {
  const { authenticated, isAdmin, features } = useAuthContext();
  const items = relatedNavItems(hrefs, {
    capabilities: features,
    isAdmin: authenticated === true && isAdmin === true,
  });
  if (items.length === 0) {
    // While the auth probe (which carries the capability map) is still
    // resolving, hold the row's height instead of rendering nothing:
    // gated links appear on resolve, and popping a row in above the page
    // body is a layout shift on every visit.  Empty, and hidden from
    // assistive tech — it offers nothing until we know what is offered.
    if (authenticated === null || authenticated === undefined) {
      return <div className="shell-related shell-related--pending" aria-hidden="true" />;
    }
    return null;
  }
  return (
    <nav className="shell-related" aria-label={`${label} pages`}>
      <span className="shell-related-label">{label}:</span>
      <ul className="shell-related-list">
        {items.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="ds-link" title={item.hint || undefined}>
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
