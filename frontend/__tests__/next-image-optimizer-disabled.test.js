/**
 * Image Optimization stays disabled.
 *
 * `/_next/image` is a server-side fetch/decode surface (GHSA-2464-fhr4-w9xw
 * was an RCE in it).  This app uses no `next/image`, so the endpoint was pure
 * attack surface.  `images.unoptimized: true` makes Next's own handler answer
 * 404 before it validates params or fetches anything; nginx blocks the path
 * too (deploy/nginx/chaseupside-proxy.conf, pinned by
 * tests/deploy/test_nginx_next_image_blocked.py).
 *
 * If you need optimized images, remove BOTH layers in the same change —
 * with only this one removed, every optimized <Image> would 404 at nginx.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import nextConfig from "../next.config.mjs";

const FRONTEND = path.resolve(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "lib"];
const SOURCE_EXT = /\.(js|jsx|mjs|ts|tsx)$/;

function sourceFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (SOURCE_EXT.test(entry.name)) out.push(full);
  }
  return out;
}

describe("Next.js image optimizer", () => {
  it("is disabled in next.config.mjs", () => {
    expect(nextConfig.images?.unoptimized).toBe(true);
  });

  it("is not re-opened to remote hosts or SVG", () => {
    expect(nextConfig.images?.remotePatterns ?? []).toEqual([]);
    expect(nextConfig.images?.domains ?? []).toEqual([]);
    expect(nextConfig.images?.dangerouslyAllowSVG).not.toBe(true);
    expect(nextConfig.images?.loader ?? "default").toBe("default");
  });

  it("no frontend source builds /_next/image URLs by hand", () => {
    const offenders = SOURCE_DIRS.flatMap((d) => sourceFiles(path.join(FRONTEND, d))).filter(
      (file) => fs.readFileSync(file, "utf8").includes("/_next/image"),
    );
    expect(offenders).toEqual([]);
  });
});
