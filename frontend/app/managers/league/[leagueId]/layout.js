import { pageMetadata } from "@/lib/page-metadata";

export const metadata = pageMetadata("/managers/league/[leagueId]");

export default function Layout({ children }) {
  return children;
}
