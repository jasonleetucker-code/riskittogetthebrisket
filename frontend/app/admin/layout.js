import { pageMetadata } from "@/lib/page-metadata";

export const metadata = pageMetadata("/admin");

export default function Layout({ children }) {
  return children;
}
