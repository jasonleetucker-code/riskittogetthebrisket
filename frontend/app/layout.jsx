import "./globals.css";
import AppShellWrapper from "./AppShellWrapper";

export const metadata = {
  title: "Dynasty Trade Calculator",
  description: "React + Next.js frontend for dynasty rankings and trade evaluation",
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
