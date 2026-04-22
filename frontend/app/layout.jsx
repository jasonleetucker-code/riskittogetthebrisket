import "./globals.css";
import AppShellWrapper from "./AppShellWrapper";

export const metadata = {
  title: "Dynasty Trade Calculator",
  description: "React + Next.js frontend for dynasty rankings and trade evaluation",
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
        <AppShellWrapper>{children}</AppShellWrapper>
      </body>
    </html>
  );
}
