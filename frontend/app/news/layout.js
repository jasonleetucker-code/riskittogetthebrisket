import { pageMetadata } from "@/lib/page-metadata";

export const metadata = pageMetadata("/news");

export default function Layout({ children }) {
  return children;
}
