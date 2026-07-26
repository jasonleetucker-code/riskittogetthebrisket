import "./globals.css";
import { Inter, JetBrains_Mono } from "next/font/google";
import AppShellWrapper from "./AppShellWrapper";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";
import PullToRefresh from "@/components/PullToRefresh";

// Redesign R0: actually load the fonts the token layer names. The audit
// found Inter + JetBrains Mono referenced in CSS but never loaded — every
// platform silently fell back to Segoe UI / Courier-class stacks. next/font
// self-hosts both at build time (zero runtime requests), exposes them as
// CSS variables consumed by tokens.css (--font-ui / --font-data) and by the
// legacy --font / --mono stacks in globals.css, and uses display:swap so
// text renders immediately on first visit.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata = {
  title: "Dynasty Trade Calculator",
  description: "React + Next.js frontend for dynasty rankings and trade evaluation",
  manifest: "/manifest.webmanifest",
  // Tell Safari + Chrome this is an installable "app".  The
  // display / theme color come from the PWA manifest for the
  // home-screen launcher; these tags hint the same to browser
  // chrome when the page is rendered inside a regular tab.
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Brisket",
  },
  // Theme color matches the manifest's ``theme_color`` — drives
  // the Android Chrome URL bar tint when the user is on the site.
  themeColor: "#4F2185",
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
      <body>
        <ServiceWorkerRegistrar />
        <PullToRefresh />
        <AppShellWrapper>{children}</AppShellWrapper>
      </body>
    </html>
  );
}
