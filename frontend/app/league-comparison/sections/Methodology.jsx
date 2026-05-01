"use client";

/**
 * Methodology — explains the formulas and limitations to anyone
 * inspecting the numbers.  Static text, but pulls live config values
 * (sample sizes, seasons) from the data payload so the explanation
 * always matches what was actually computed.
 */
export default function Methodology({ data }) {
  const meta = data?.meta || {};
  const samples = meta.sampleSizes || {};
  const seasonsAvail = (meta.seasonsAvailable || []).join(", ") || "—";
  const seasonsReq = (meta.seasonsRequested || []).join(", ") || "—";
  const idp = data?.idp || {};

  return (
    <div className="card">
      <h2 className="section-title">Methodology</h2>

      <h3 style={{ marginTop: "var(--space-md)" }}>What this page does</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        For each league, we fetch its actual <code>scoring_settings</code>
        directly from Sleeper, then apply those settings to historical NFL
        weekly stats to compute fantasy points <em>under that league's own
        rules</em>.  We then sample the top performers per position,
        summarize the distribution, and compare the two leagues to see
        whether your custom scoring keeps positional value reasonably
        aligned with a standard baseline.
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Data sources</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Weekly NFL stats are pulled from nflverse where available, with
        an automatic fallback to the Sleeper stats API for any season
        nflverse hasn't yet published (typically the most-recent season).
        Sleeper field names are translated to the nflverse schema so the
        same scoring engine handles both — every category modeled
        upstream is honored regardless of which source fed the row.
        The <em>Seasons included</em> tag at the top shows which source
        produced each season's data.
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Sample sizes</h3>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li>Top {samples.QB || 24} QBs</li>
        <li>Top {samples.RB || 24} RBs</li>
        <li>Top {samples.WR || 36} WRs</li>
        <li>Top {samples.TE || 12} TEs</li>
        <li>Top {samples.FLEX || 96} offensive flex (RB ∪ WR ∪ TE, QBs excluded)</li>
      </ul>

      <h3 style={{ marginTop: "var(--space-md)" }}>Week range</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Each season uses regular-season <strong>weeks 1–17 only</strong>.
        Week 18 is dropped because most playoff-bound teams rest starters,
        which would distort top-of-the-board scoring.  Postseason rows are
        also excluded — they're already filtered out by the same gate.
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Player ranking — blended score</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Every player's season is reduced to a single <strong>blended
        score</strong> that mixes total fantasy points (volume — what they
        actually scored) with their per-game pace extrapolated to a full
        17-week season (pace — what they'd have scored at full
        availability).  This rewards a player who missed weeks at an
        elite pace without erasing the volume signal a workhorse 17-game
        starter brings.
      </p>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li>
          Formula: <code>0.5 × total_points + 0.5 × (ppg × 17)</code>
          when <em>games_played ≥ 8</em>; otherwise just total points.
        </li>
        <li>
          The 8-game minimum prevents a tiny-sample outlier (e.g. one
          30-point week) from inflating PPG.  Below 8 games, the player
          is ranked on volume alone.
        </li>
        <li>
          A 17-game starter has ppg×17 == total, so blended == total.
          Players who missed weeks slot between their actual total and
          their full-season-equivalent total.
        </li>
      </ul>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Top-N samples and all per-position metrics (average, median, P25,
        P75, replacement, elite, replacement-adj) are computed from
        blended scores, not raw totals.
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Seasons</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Requested: <strong>{seasonsReq}</strong>. Available: <strong>{seasonsAvail}</strong>.
        Each available season is weighted <strong>equally</strong> in the
        combined result — no recency weighting.  If a season is missing
        from the upstream data source, the remaining seasons each absorb
        its weight proportionally (e.g. 3 seasons → each counts 1/3).
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Position metrics (per top-N sample)</h3>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li><strong>Average</strong> — mean fantasy points</li>
        <li><strong>Median</strong> — 50th-percentile fantasy points</li>
        <li><strong>P25 / P75</strong> — 25th / 75th percentile</li>
        <li><strong>Replacement level</strong> — the Nth player's points (e.g. QB24)</li>
        <li><strong>Elite</strong> — mean of the top 3</li>
        <li><strong>Replacement-adjusted</strong> — average minus replacement level (separation between starters and the bottom of the pool)</li>
      </ul>

      <h3 style={{ marginTop: "var(--space-md)" }}>Blended scores — two methods</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Both are computed and shown side-by-side:
      </p>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li>
          <strong>Legacy / Simple:</strong> <code>(average + median) / 2</code> —
          the original heuristic, preserved as a reference.
        </li>
        <li>
          <strong>Improved:</strong>{" "}
          <code>0.35·median + 0.25·average + 0.20·P75 + 0.10·P25 + 0.10·replacement_adj</code>{" "}
          — more robust because the median anchors central tendency, the
          percentiles capture distribution shape, and the replacement-adjusted
          term rewards positions whose starters are well-separated from the
          replacement-level player.
        </li>
      </ul>

      <h3 style={{ marginTop: "var(--space-md)" }}>Positional shares</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        For each league, every position's blended score is divided by the
        total of all four positions to get a percentage share.  We then
        compare your share against the baseline share — both as an absolute
        difference (in percentage points) and as a relative percentage.
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Status labels</h3>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li>≤ 0.5 pp difference — <strong>Excellent match</strong></li>
        <li>≤ 1.5 pp — <strong>Good match</strong></li>
        <li>≤ 3.0 pp — <strong>Slightly high / Slightly low</strong></li>
        <li>≤ 5.0 pp — <strong>High / Low</strong></li>
        <li>&gt; 5.0 pp — <strong>Too high / Too low</strong></li>
      </ul>

      <h3 style={{ marginTop: "var(--space-md)" }}>Similarity score (0..100)</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        Total share deviation across QB/RB/WR/TE (sum of absolute differences
        in percentage points), plus 0.4× the relative flex-pool deviation,
        mapped through these bands:
      </p>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li>≤ 2 → <strong>95–100</strong> · Extremely close · distortion: Low</li>
        <li>≤ 5 → <strong>85–94</strong> · Very close · distortion: Low</li>
        <li>≤ 10 → <strong>75–84</strong> · Some noticeable differences · distortion: Moderate</li>
        <li>≤ 20 → <strong>60–74</strong> · Meaningfully different · distortion: High</li>
        <li>&gt; 20 → <strong>&lt; 60</strong> · Very distorted · distortion: Severe</li>
      </ul>

      <h3 style={{ marginTop: "var(--space-md)" }}>IDP comparison</h3>
      <p className="text-sm" style={{ lineHeight: 1.6 }}>
        IDP is <strong>scaffolded but not yet enabled</strong>. {idp.message}
      </p>

      <h3 style={{ marginTop: "var(--space-md)" }}>Known limitations</h3>
      <ul className="text-sm" style={{ paddingLeft: 20, lineHeight: 1.6 }}>
        <li>Compares fantasy <em>points</em> only — not usage, opportunity, or roster construction.</li>
        <li>Kickers and team defenses are excluded — out of scope for positional balance.</li>
        <li>Sleeper scoring keys not modeled by the engine (rare custom bonuses) are zeroed; these are listed in the warnings panel above when present and non-zero.</li>
        <li>The most-recent season may use Sleeper as the data source until nflverse publishes — both sources feed the same scoring engine, so results are directly comparable.</li>
        <li>Recommendations are heuristic culprit-hints, not prescriptive — they never auto-modify scoring settings.</li>
      </ul>
    </div>
  );
}
