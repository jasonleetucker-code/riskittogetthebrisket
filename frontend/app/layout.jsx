import "./globals.css";
import localFont from "next/font/local";
import AppShellWrapper from "./AppShellWrapper";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";
import PullToRefresh from "@/components/PullToRefresh";
import { EARLY_CONTRACT_SCRIPT } from "@/lib/early-contract";

// Approved Sports Network typography, locally vendored with OFL licenses.
// No font CDN requests or build-time network access. Plex provides readable
// interface/prose text and tabular data; Barlow supplies the broadcast identity.
const plex = localFont({
  src: "./fonts/ibm-plex-sans-latin-var.woff2",
  weight: "100 700",
  display: "swap",
  variable: "--font-sans",
  adjustFontFallback: "Arial",
});
const broadcast = localFont({
  src: "./fonts/barlow-condensed-bold-latin.woff2",
  weight: "700",
  display: "swap",
  variable: "--font-broadcast",
  fallback: ["Impact", "Arial Narrow", "sans-serif"],
  adjustFontFallback: false,
});

export const metadata = {
  // Brand name, matching the top bar, the PWA manifest and the
  // apple-web-app title.  This said "Dynasty Trade Calculator" — a
  // name nothing else in the product uses — so every browser tab and
  // bookmark disagreed with the site itself.
  title: "Chase Upside",
  description:
    "Dynasty fantasy football rankings, trade analysis and league history",
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
};

// Explicit viewport so Next.js does not fall back to a stale default.
// viewport-fit=cover lets content extend under the iOS home-indicator,
// and we leave user-scalable enabled so accessibility zoom still works.
export const viewport = {
  themeColor: "#0b2130",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${plex.variable} ${broadcast.variable}`}>
      <head>
        {/* Starts the Rankings/Trade board request during HTML parse, so it
            overlaps the chunk download and hydration instead of waiting for
            them; the fetch layer adopts it (lib/early-contract.js). Inert on
            every other route. */}
        <script dangerouslySetInnerHTML={{ __html: EARLY_CONTRACT_SCRIPT }} />
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
