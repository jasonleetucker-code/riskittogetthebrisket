import { pageMetadata } from "@/lib/page-metadata";

export const metadata = pageMetadata("/players/[playerId]");

export default function Layout({ children }) {
  return children;
}
