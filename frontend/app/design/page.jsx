/**
 * /design — living implementation reference for approved PSI / Direction A.
 *
 * Dev/reference route: linked from no navigation, noindexed. Renders every
 * token ramp and component state so later phases (and reviewers) can see
 * the system at a glance. Isolated examples are fixtures, not live product
 * data. Reuse the approved direction; this route does not authorize a redesign.
 */
import DesignGallery from "./DesignGallery";

export const metadata = {
  title: "Design System — Chase Upside",
  robots: { index: false, follow: false },
};

export default function DesignPage() {
  return <DesignGallery />;
}
