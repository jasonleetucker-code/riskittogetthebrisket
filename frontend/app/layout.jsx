import "./globals.css";
import Link from "next/link";
import { Sora, IBM_Plex_Mono } from "next/font/google";

export const metadata = {
  title: "Risk It to Get the Brisket",
  description: "Modern migration shell for dynasty rankings, value intelligence, and trade workflow.",
};

const sora = Sora({
  subsets: ["latin"],
  variable: "--font-sora",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-plex-mono",
  display: "swap",
  weight: ["400", "500", "600"],
});

const nav = [
  { href: "/", label: "Home" },
  { href: "/rankings", label: "Rankings" },
  { href: "/trade", label: "Trade" },
  { href: "/league", label: "League" },
];

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className={`${sora.variable} ${plexMono.variable}`}>
        <div className="shell-bg-orb shell-bg-orb-a" aria-hidden="true" />
        <div className="shell-bg-orb shell-bg-orb-b" aria-hidden="true" />
        <header className="topbar">
          <div className="topbar-inner">
            <div className="brand-wrap">
              <div className="brand-eyebrow">Risk It to Get the Brisket</div>
              <div className="brand">Dynasty Value Engine</div>
            </div>
            <nav className="nav">
              {nav.map((item) => (
                <Link key={item.href} href={item.href} className="nav-link" prefetch={false}>
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="runtime-strip">
            <span className="runtime-pill runtime-pill-live">Live Runtime: FastAPI + Static Shell</span>
            <span className="runtime-pill">Public: `/` + `/league/*`</span>
            <span className="runtime-pill">Private: `/app` + `/rankings` + `/trade`</span>
          </div>
        </header>
        <main className="main-shell">{children}</main>
        <footer className="shell-footer">
          <div className="shell-footer-inner">
            <span className="mono">Next Migration Shell</span>
            <span className="muted">Authoritative production routing remains backend + static unless runtime mode is explicitly switched.</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
