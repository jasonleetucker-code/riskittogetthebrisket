import { pageMetadata } from "@/lib/page-metadata";

export const metadata = pageMetadata("/auction/[roomId]");

export default function Layout({ children }) {
  return children;
}
