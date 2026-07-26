/**
 * /design — living style reference for the R0 design system.
 *
 * Dev/reference route: linked from no navigation, noindexed. Renders every
 * token ramp and component state so later phases (and reviewers) can see
 * the system at a glance. This page is the first impression of the new
 * design language — keep it as disciplined as the system it documents.
 */
import DesignGallery from "./DesignGallery";

export const metadata = {
  title: "Design System — Brisket",
  robots: { index: false, follow: false },
};

export default function DesignPage() {
  return <DesignGallery />;
}
