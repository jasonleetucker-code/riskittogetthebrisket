// ROS source registry — read-only mirror of ``src/ros/sources/__init__.py``.
//
// pytest parity check: ``tests/ros/test_sources_registry_parity.py``.
//
// Add a new source:
//   1. Implement the Python adapter under ``src/ros/sources/<key>.py``.
//   2. Add an entry to ``ROS_SOURCES`` in the Python registry.
//   3. Mirror it here with camelCase field names.
//   4. Run the parity test.
//
// Field mapping (Python → JS):
//   key                       → key
//   display_name              → displayName
//   source_url                → sourceUrl
//   source_type               → sourceType
//   scoring_format            → scoringFormat
//   is_superflex              → isSuperflex
//   is_2qb                    → is2qb
//   is_te_premium             → isTePremium
//   is_idp                    → isIdp
//   is_ros                    → isRos
//   is_dynasty                → isDynasty
//   is_projection_source      → isProjectionSource
//   base_weight               → baseWeight
//   stale_after_hours         → staleAfterHours
//   enabled                   → enabled
export const ROS_SOURCES = [
  {
    key: "fantasyProsRosSf",
    displayName: "FantasyPros Dynasty SF (ROS proxy)",
    sourceUrl: "https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php",
    sourceType: "dynasty_proxy",
    scoringFormat: "ppr",
    isSuperflex: true,
    is2qb: false,
    isTePremium: false,
    isIdp: false,
    isRos: false,
    isDynasty: true,
    isProjectionSource: false,
    baseWeight: 0.85,
    staleAfterHours: 168,
    enabled: true,
  },
  {
    key: "draftSharksRosSf",
    displayName: "Draft Sharks ROS Superflex",
    sourceUrl: "https://www.draftsharks.com/rankings/rest-of-season",
    sourceType: "ros",
    scoringFormat: "ppr",
    isSuperflex: true,
    is2qb: false,
    isTePremium: false,
    isIdp: false,
    isRos: true,
    isDynasty: false,
    isProjectionSource: true,
    baseWeight: 1.25,
    staleAfterHours: 24,
    enabled: true,
  },
  {
    key: "fantasyProsRosIdp",
    displayName: "FantasyPros Dynasty IDP (ROS proxy)",
    sourceUrl: "https://www.fantasypros.com/nfl/rankings/dynasty-idp.php",
    sourceType: "dynasty_proxy",
    scoringFormat: "ppr",
    isSuperflex: false,
    is2qb: false,
    isTePremium: false,
    isIdp: true,
    isRos: false,
    isDynasty: true,
    isProjectionSource: false,
    baseWeight: 1.05,
    staleAfterHours: 168,
    enabled: true,
  },
  {
    key: "footballGuysRosIdp",
    displayName: "Footballguys IDP (ROS proxy)",
    sourceUrl: "https://www.footballguys.com/rankings/idp",
    sourceType: "dynasty_proxy",
    scoringFormat: "ppr",
    isSuperflex: false,
    is2qb: false,
    isTePremium: false,
    isIdp: true,
    isRos: false,
    isDynasty: true,
    isProjectionSource: true,
    baseWeight: 0.85,
    staleAfterHours: 168,
    enabled: true,
  },
  {
    key: "ffc2qbAdp",
    displayName: "Fantasy Football Calculator 2QB ADP",
    sourceUrl: "https://fantasyfootballcalculator.com/adp/2qb",
    sourceType: "adp",
    scoringFormat: "ppr",
    isSuperflex: false,
    is2qb: true,
    isTePremium: false,
    isIdp: false,
    isRos: false,
    isDynasty: false,
    isProjectionSource: false,
    baseWeight: 0.70,
    staleAfterHours: 24,
    enabled: true,
  },
];

export function rosSourceKeys() {
  return ROS_SOURCES.map((s) => s.key);
}

export function getRosSource(key) {
  return ROS_SOURCES.find((s) => s.key === key) || null;
}
