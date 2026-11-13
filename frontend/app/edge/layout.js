import { pageMetadata } from "@/lib/page-metadata";

export const metadata = pageMetadata("/edge");

export default function Layout({ children }) {
  return children;
}
