/**
 * PWA manifest for the Next.js App Router.
 *
 * ``app/manifest.js`` is a special file Next resolves at build time
 * and serves at ``/manifest.webmanifest``.  Pairs with the
 * ``manifest.ts`` ``Metadata`` entry (see ``layout.jsx``) so the
 * browser picks up ``<link rel="manifest">`` automatically.
 *
 * Icons reference ``public/icons/*`` which ship static.
 */
export default function manifest() {
  return {
    name: "Risk It To Get The Brisket",
    short_name: "Brisket",
    description:
      "Dynasty fantasy football terminal — rankings, trade calculator, league analysis.",
    start_url: "/",
    id: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0f0a1a",
    theme_color: "#4F2185",
    categories: ["sports", "productivity"],
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
