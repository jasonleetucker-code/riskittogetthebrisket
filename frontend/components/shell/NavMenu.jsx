"use client";

/**
 * NavMenu — accessible top-bar dropdown for a nav group.
 *
 * SPLIT TRIGGER: a link to the group's primary destination plus a
 * separate chevron button that opens the menu.  Hover still opens the
 * menu (with a close delay) for mouse users.
 *
 * The whole trigger used to be one button, so clicking "Trade" did
 * nothing but open a list — the top-level labels were signposts you
 * could not actually walk through.  The nav model has always asserted
 * that a group's href is one of its own items ("parent click lands
 * in-group", pinned in __tests__/nav-model.test.js), so this makes the
 * rendering honour a contract the data already declared.  It is also
 * what lets high-traffic pages sit inside a group without paying an
 * extra click: /rankings is one click from "Rankings", not two.
 *
 * A11y: the chevron owns aria-expanded/aria-haspopup, so screen
 * readers get "Rankings, link" and "Rankings menu, collapsed, button"
 * as separate, correctly-typed controls.  ArrowDown/Up from either
 * half rove through role="menuitem" links, Escape closes and refocuses
 * the disclosure, focus-out and route change close.
 *
 * Props:
 *   label       group label
 *   href        group's primary destination (optional — omit for a
 *               menu with no landing page, e.g. System)
 *   items       [{href, label, hint, section?}] — leaf destinations
 *   active      boolean — group contains the current route
 *   pathname    current pathname (for aria-current on items)
 *   align       "left" | "right" (menu edge)
 *   renderExtra optional node appended after the items (e.g. sign out)
 */
import Link from "next/link";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ds";
import { isNavActive } from "@/lib/nav-model";

export default function NavMenu({
  label,
  href = null,
  items,
  active = false,
  pathname,
  align = "left",
  renderExtra = null,
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const triggerRef = useRef(null);
  const closeTimer = useRef(null);
  // Hover-open must not make the follow-up click snap the menu shut:
  // a click while hover-opened CONVERTS the open to click-owned (stays
  // open); only a genuine second click closes. Keyboard activation
  // never sets the flag, so Enter/Space toggle cleanly.
  const openedByHover = useRef(false);

  const cancelClose = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);
  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), 140);
  }, [cancelClose]);

  // Close on route change and on unmount-cleanup of the timer.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);
  useEffect(() => cancelClose, [cancelClose]);

  const onKeyDown = useCallback(
    (e) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const nodes = Array.from(
          wrapRef.current?.querySelectorAll('[role="menuitem"]') || []
        );
        if (nodes.length === 0) return;
        const idx = nodes.indexOf(document.activeElement);
        const next =
          e.key === "ArrowDown"
            ? nodes[(idx + 1) % nodes.length]
            : nodes[(idx - 1 + nodes.length) % nodes.length];
        setOpen(true);
        next?.focus();
      }
    },
    []
  );

  const onBlur = useCallback((e) => {
    if (wrapRef.current && !wrapRef.current.contains(e.relatedTarget)) {
      setOpen(false);
    }
  }, []);

  let lastSection = null;

  return (
    <span
      ref={wrapRef}
      className="shell-nav-item"
      data-open={open || undefined}
      onMouseEnter={() => {
        cancelClose();
        if (!open) openedByHover.current = true;
        setOpen(true);
      }}
      onMouseLeave={scheduleClose}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
    >
      {href ? (
        <Link
          href={href}
          className={`shell-nav-link shell-nav-link--group${active ? " shell-nav-link--active" : ""}`}
          aria-current={active && isNavActive(href, pathname) ? "page" : undefined}
        >
          {label}
        </Link>
      ) : (
        <span className={`shell-nav-link shell-nav-link--group${active ? " shell-nav-link--active" : ""}`}>
          {label}
        </span>
      )}
      <button
        ref={triggerRef}
        type="button"
        className={`shell-nav-caret-btn${active ? " shell-nav-link--active" : ""}`}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${label} menu`}
        onClick={() => {
          if (!open) {
            openedByHover.current = false;
            setOpen(true);
          } else if (openedByHover.current) {
            openedByHover.current = false; // convert hover-open to click-owned
          } else {
            setOpen(false);
          }
        }}
      >
        <Icon name="chevron-down" size={10} className="shell-nav-caret" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={label}
          className={`shell-menu${align === "right" ? " shell-menu--right" : ""}`}
        >
          {items.map((item) => {
            const sectionHeader =
              item.section && item.section !== lastSection ? (
                <div key={`sec-${item.section}`} className="shell-menu-section">
                  {item.section}
                </div>
              ) : null;
            lastSection = item.section || lastSection;
            const current = isNavActive(item.href, pathname);
            return (
              <Fragment key={item.href}>
                {sectionHeader}
                <Link
                  href={item.href}
                  role="menuitem"
                  className="shell-menu-item"
                  aria-current={current ? "page" : undefined}
                >
                  <span>{item.label}</span>
                  {item.hint ? (
                    <span className="shell-menu-item-hint">{item.hint}</span>
                  ) : null}
                </Link>
              </Fragment>
            );
          })}
          {renderExtra}
        </div>
      ) : null}
    </span>
  );
}
