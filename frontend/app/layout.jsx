import "./globals.css";
import AppShellWrapper from "./AppShellWrapper";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";

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
    <html lang="en">
      <body>
        <ServiceWorkerRegistrar />
        <AppShellWrapper>{children}</AppShellWrapper>
      </body>
    </html>
  );
}
