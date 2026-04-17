// Dynamic robots.txt.  Allows crawling of all public routes (the
// entire /league surface + /trades + /draft-capital) and disallows
// the private surfaces that exist behind auth.

function _origin() {
  return (
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.PUBLIC_SITE_URL ||
    "https://riskittogetthebrisket.org"
  ).replace(/\/$/, "");
}

export default function robots() {
  const origin = _origin();
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/league", "/league/", "/trades", "/draft-capital"],
        disallow: [
          "/api/",
          "/rankings",
          "/trade",
          "/edge",
          "/finder",
          "/rosters",
          "/settings",
          "/login",
        ],
      },
    ],
    sitemap: `${origin}/sitemap.xml`,
  };
}
