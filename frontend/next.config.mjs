import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Allow deploys to build into a staging directory (e.g. ".next.new")
// and then atomically rename it onto ".next" after the service is
// stopped.  This prevents the running Next.js server from observing a
// half-rewritten .next/ directory, which is what produces the
// ChunkLoadError / 400 Bad Request failures on /_next/static/chunks/*.
// At serve time the systemd unit runs `next start` with no override so
// this falls back to the standard ".next" location.
const DIST_DIR = process.env.NEXT_DIST_DIR || ".next";

/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: DIST_DIR,
  turbopack: {
    root: __dirname,
  },
  async redirects() {
    return [
      {
        // Legacy route.  This used to be `app/draft-capital/page.jsx`
        // calling `redirect()` inside a React render, which meant the
        // first leg cost a full route invocation — measured 1445ms
        // TTFB against 7-35ms on every other route, because the
        // redirect target (/league) is a server component that awaits
        // the multi-MB public contract.  Emitting the redirect from
        // the routing layer costs sub-millisecond instead, and a
        // permanent (308) redirect is cacheable by the browser so
        // repeat visits skip the leg entirely.
        source: "/draft-capital",
        destination: "/league?tab=draft-capital",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
