import "./globals.css";
import Link from "next/link";

export const metadata = {
  title: "Dynasty Trade Calculator",
  description: "React + Next.js frontend for dynasty rankings and trade evaluation",
};

const nav = [
  { href: "/", label: "Home" },
  { href: "/rankings", label: "Rankings" },
  { href: "/trade", label: "Trade" },
  { href: "/login", label: "Login" },
];

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <div className="brand">Dynasty Trade Calculator</div>
            <nav className="nav">
              {nav.map((item) => (
                <Link key={item.href} href={item.href} className="nav-link">
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="main-shell">{children}</main>
      </body>
    </html>
  );
}
