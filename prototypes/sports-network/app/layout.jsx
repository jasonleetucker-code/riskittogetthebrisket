import "./styles.css";
import localFont from "next/font/local";
const display = localFont({
  src: "../public/fonts/barlow-bold.woff2",
  weight: "700",
  variable: "--font-display",
  display: "swap",
  fallback: ["Impact", "Arial Narrow", "sans-serif"],
  adjustFontFallback: false,
});
const body = localFont({
  src: "../public/fonts/plex-sans.woff2",
  weight: "100 700",
  variable: "--font-body",
  display: "swap",
  adjustFontFallback: "Arial",
});
export const metadata = {
  title: "Chase Upside — Sports Network study",
  robots: { index: false, follow: false },
};
export default function Layout({ children }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body>{children}</body>
    </html>
  );
}
