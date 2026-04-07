"use client";

import Link from "next/link";
import { useCallback } from "react";
import AppShell, { useApp } from "@/components/AppShell";

const nav = [
  { href: "/", label: "Home" },
  { href: "/rankings", label: "Rankings" },
  { href: "/trade", label: "Trade" },
  { href: "/settings", label: "Settings" },
  { href: "/login", label: "Login" },
];

function NavBar() {
  const { openSearch } = useApp();

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">Dynasty Trade Calculator</div>
        <nav className="nav">
          {nav.map((item) => (
            <Link key={item.href} href={item.href} className="nav-link">
              {item.label}
            </Link>
          ))}
          <button
            className="nav-link button-reset"
            onClick={openSearch}
            title="Search players (press /)"
            style={{ cursor: "pointer", opacity: 0.7 }}
          >
            /
          </button>
        </nav>
      </div>
    </header>
  );
}

export default function AppShellWrapper({ children }) {
  return (
    <AppShell>
      <NavBar />
      <main className="main-shell">{children}</main>
    </AppShell>
  );
}
