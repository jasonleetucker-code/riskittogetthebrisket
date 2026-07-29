import "./globals.css";
import localFont from "next/font/local";
import AppShellWrapper from "./AppShellWrapper";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";
import PullToRefresh from "@/components/PullToRefresh";

// Redesign R0: actually load the fonts the token layer names. The audit
// found Inter + JetBrains Mono referenced in CSS but never loaded — every
// platform silently fell back to Segoe UI / Courier-class stacks.
//
// next/font/local with CHECKED-IN woff2 assets (app/fonts/): the build
// must never contact fonts.googleapis.com — production builders are
// network-restricted, so next/font/google would fail the build. The
// vendored files are the official variable fonts, latin subset only
// (~48 KB + ~40 KB); accented latin-1 glyphs are included via U+00xx,
// anything beyond falls back through the stacks below. Both are exposed
// as CSS variables consumed by tokens.css (--font-ui / --font-data) and
// by the legacy --font / --mono stacks in globals.css; display:swap so
// text renders immediately on first visit.
const inter = localFont({
  src: "./fonts/inter-latin-var.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-sans",
});
const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin-var.woff2",
  weight: "100 800",
  style: "normal",
  display: "swap",
  variable: "--font-mono",
});

export const metadata = {
  // Brand name, matching the top bar, the PWA manifest and the
  // apple-web-app title.  This said "Dynasty Trade Calculator" — a
  // name nothing else in the product uses — so every browser tab and
  // bookmark disagreed with the site itself.
  title: "Chase Upside",
  description: "Dynasty fantasy football rankings, trade analysis and league history",
  manifest: "/manifest.webmanifest",
  // Tell Safari + Chrome this is an installable "app".  The
  // display / theme color come from the PWA manifest for the
  // home-screen launcher; these tags hint the same to browser
  // chrome when the page is rendered inside a regular tab.
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Chase Upside",
  },
  // Theme color matches the manifest's ``theme_color`` — drives
  // the Android Chrome URL bar tint when the user is on the site.
  // Terminal: the mobile browser-chrome colour follows the page surface,
  // not a franchise hex. Was #4F2185 (Vikings purple).
  themeColor: "#0b0d10",
};

// Explicit viewport so Next.js does not fall back to a stale default.
// viewport-fit=cover lets content extend under the iOS home-indicator,
// and we leave user-scalable enabled so accessibility zoom still works.
export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        {/* Player headshots + team logos come from sleepercdn.com —
            the one third-party origin.  Warming the connection saves
            a DNS+TLS round-trip before the first avatar paints. */}
        <link
          rel="preconnect"
          href="https://sleepercdn.com"
          crossOrigin="anonymous"
        />
      </head>
      <body>
        <ServiceWorkerRegistrar />
        <PullToRefresh />
        <AppShellWrapper>{children}</AppShellWrapper>
      </body>
    </html>
  );
}
