"use client";

// Package Builder (C7-PKGB-01) — packages built to the user's request.
//
// Display only: every constraint is applied during generation on the server
// (src/trade/package_builder.py over the finder's enumeration) and every
// number comes from POST /api/trade/package-builder.  Recommendation only —
// there is no send action; "Open in Trade Calculator" hands a package to /trade.

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  SegmentedControl,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildShareUrl } from "@/lib/trade-share";
import {
  UNKNOWN,
  fmtSignedInt,
  fmtSignedPct,
  lineupLine,
  verdictLines,
} from "@/lib/best-offers";
import {
  PACKAGE_POSITIONS,
  buildRequest,
  noResultText,
  togglePosition,
} from "@/lib/package-builder";
import {
  emptyRefinement,
  loadRefinement,
  refinementKey,
  saveRefinement,
  toggleExclude,
  toggleLock,
} from "@/lib/trade-refinement";
import {
  OutgoingRefinement,
  RefinementBar,
} from "@/components/trade/RefinementControls";
import styles from "./package-builder.module.css";

const EVIDENCE_OPTIONS = [
  { value: "any", label: "Fair for you" },
  { value: "external", label: "Also even for them externally" },
];
const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

function calcUrl(myTeam, pkg) {
  const asName = (a) => a.boardRowName || a.name;
  try {
    return buildShareUrl({
      sides: [
        { name: myTeam || "You", players: pkg.send.map(asName) },
        { name: pkg.opponent, players: pkg.receive.map(asName) },
      ],
    });
  } catch {
    return null;
  }
}

export default function PackageBuilderView({
  myTeam,
  leagueKey,
  ownerKey,
  teams = [],
}) {
  const storageKey = refinementKey({
    owner: ownerKey,
    leagueKey,
    surface: "package-builder",
    context: myTeam,
  });
  const [target, setTarget] = useState("");
  const [opponent, setOpponent] = useState("");
  const [outgoing, setOutgoing] = useState([]);
  const [positions, setPositions] = useState([]);
  const [maxSide, setMaxSide] = useState(3);
  const [allowPicks, setAllowPicks] = useState(false);
  const [evidence, setEvidence] = useState("any");
  const [useTeamContext, setUseTeamContext] = useState(true);
  const [refinement, setRefinement] = useState(emptyRefinement);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    seq.current += 1; // drop any response for the previous team or league
    setResult(null);
    setRunning(false);
    setOutgoing([]);
    setRefinement(loadRefinement(storageKey));
  }, [storageKey]);

  const myRoster = useMemo(
    () => (teams.find((t) => t.name === myTeam)?.players || []).slice().sort(),
    [teams, myTeam],
  );
  const otherPlayers = useMemo(
    () =>
      teams
        .filter((t) => t.name !== myTeam && (!opponent || t.name === opponent))
        .flatMap((t) => t.players || [])
        .sort(),
    [teams, myTeam, opponent],
  );

  async function run(nextRefinement = refinement) {
    if (!myTeam) return;
    const mine = ++seq.current;
    setRunning(true);
    setError("");
    try {
      const res = await fetch("/api/trade/package-builder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(
          withValuationMode(
            buildRequest({
              myTeam,
              leagueKey,
              target,
              opponent,
              outgoing,
              positions,
              maxSide,
              allowPicks,
              evidence,
              useTeamContext,
              refinement: nextRefinement,
            }),
          ),
        ),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok)
        throw new Error(data?.error || `Request failed (${res.status})`);
      if (mine === seq.current) setResult(data);
    } catch (err) {
      if (mine === seq.current) setError(err?.message || "Request failed");
    } finally {
      if (mine === seq.current) setRunning(false);
    }
  }

  function applyRefinement(next) {
    setRefinement(next);
    saveRefinement(storageKey, next);
    if (result) void run(next);
  }
  const refine = {
    onLock: (name) => applyRefinement(toggleLock(refinement, name)),
    onExclude: (name) => applyRefinement(toggleExclude(refinement, name)),
    onClear: () => applyRefinement(emptyRefinement()),
  };

  const packages = result?.packages || [];

  return (
    <section
      className={`${styles.view} psi-editorial`}
      aria-label="Package Builder"
    >
      <p className={styles.lede}>
        Describe the trade you want. Positions, the assets you offer, package
        size and picks shape what is generated — they are not filters on a
        finished list. Recommendations only — nothing is sent.
      </p>
      <div className={styles.form}>
        <Field label="Player or pick you want (optional)">
          <Input
            list="package-builder-targets"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="Any"
          />
        </Field>
        <datalist id="package-builder-targets">
          {otherPlayers.map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
        <Field label="From team">
          <Select
            value={opponent}
            onChange={(e) => setOpponent(e.target.value)}
          >
            <option value="">Any team</option>
            {teams
              .filter((t) => t.name !== myTeam)
              .map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
          </Select>
        </Field>
        <Field label="Most players per side">
          <Select
            value={String(maxSide)}
            onChange={(e) => setMaxSide(Number(e.target.value))}
          >
            {[1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </Field>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={allowPicks}
            onChange={(e) => setAllowPicks(e.target.checked)}
          />
          Allow draft picks
        </label>
      </div>
      <div
        className={styles.positions}
        role="group"
        aria-label="Positions you want back"
      >
        <span className={styles.groupLabel}>Positions you want back:</span>
        {PACKAGE_POSITIONS.map((p) => (
          <button
            key={p}
            type="button"
            className={styles.chip}
            aria-pressed={positions.includes(p)}
            onClick={() => setPositions((prev) => togglePosition(prev, p))}
          >
            {p}
          </button>
        ))}
        <span className={styles.muted}>{positions.length ? "" : "(any)"}</span>
      </div>
      <details className={styles.outgoing}>
        <summary>
          Assets you would offer ({outgoing.length ? outgoing.length : "all"})
        </summary>
        <div className={styles.outgoingList}>
          {myRoster.map((n) => (
            <label key={n} className={styles.check}>
              <input
                type="checkbox"
                checked={outgoing.includes(n)}
                onChange={() =>
                  setOutgoing((prev) =>
                    prev.includes(n)
                      ? prev.filter((x) => x !== n)
                      : [...prev, n],
                  )
                }
              />
              {n}
            </label>
          ))}
        </div>
      </details>
      <div className={styles.controls}>
        <SegmentedControl
          label="Evidence required"
          options={EVIDENCE_OPTIONS}
          value={evidence}
          onChange={setEvidence}
        />
        <SegmentedControl
          label="Analysis mode"
          options={CONTEXT_OPTIONS}
          value={useTeamContext ? "team" : "asset"}
          onChange={(v) => setUseTeamContext(v === "team")}
        />
        <Button onClick={() => run()} disabled={running || !myTeam}>
          {running ? "Building packages…" : "Build packages"}
        </Button>
      </div>
      <RefinementBar
        refinement={refinement}
        onLock={refine.onLock}
        onExclude={refine.onExclude}
        onClear={refine.onClear}
        disabled={running}
      />
      {error ? <Banner tone="negative">{error}</Banner> : null}
      {running ? <SkeletonTable rows={4} /> : null}
      {!running && result ? (
        <p className={styles.count} role="status">
          {packages.length} package{packages.length === 1 ? "" : "s"} found
          {result.request?.opponent ? ` with ${result.request.opponent}` : ""}.
        </p>
      ) : null}
      {!running && result && !packages.length ? (
        <EmptyState
          title={result.noResultLabel || "No package found"}
          description={
            noResultText(result) || "No package met every requirement."
          }
        />
      ) : null}
      {!running && packages.length ? (
        <ol className={styles.list}>
          {packages.map((pkg, i) => {
            const url = calcUrl(myTeam, pkg);
            const ext = pkg.external;
            return (
              <li key={`${pkg.opponent}-${i}`} className={styles.row}>
                <header className={styles.rowHead}>
                  <strong>{pkg.opponent}</strong>
                  <span className={styles.muted}>{pkg.packageSize}</span>
                  <span>
                    You{" "}
                    <strong>
                      {fmtSignedInt(pkg.canonical?.vaAdjustedGap)}
                    </strong>{" "}
                    ({pkg.canonical?.magnitude || UNKNOWN})
                  </span>
                  <span>
                    {ext
                      ? `${ext.label}: them ${fmtSignedPct(ext.opponentMarginPct)}`
                      : "No calculator shows them even"}
                  </span>
                  {pkg.confidence ? (
                    <Badge tone="outline">{pkg.confidence} confidence</Badge>
                  ) : null}
                </header>
                <div className={styles.sides}>
                  <div>
                    <span className={styles.groupLabel}>You send</span>
                    <ul className={styles.assets}>
                      {pkg.send.map((a) => (
                        <li key={a.name}>
                          {a.name} <Badge tone="neutral">{a.position}</Badge>
                          {!a.isPick ? (
                            <OutgoingRefinement
                              name={a.name}
                              refinement={refinement}
                              onLock={refine.onLock}
                              onExclude={refine.onExclude}
                              disabled={running}
                              context={`package ${i + 1}`}
                            />
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <span className={styles.groupLabel}>You receive</span>
                    <ul className={styles.assets}>
                      {pkg.receive.map((a) => (
                        <li key={a.name}>
                          {a.name} <Badge tone="neutral">{a.position}</Badge>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <ul className={styles.facts}>
                  {verdictLines(pkg).map((v) => (
                    <li key={v.calculator}>{v.text}</li>
                  ))}
                  {lineupLine(pkg.lineupImpact) ? (
                    <li>{lineupLine(pkg.lineupImpact)}</li>
                  ) : null}
                </ul>
                {url ? (
                  <Button as={Link} href={url} size="sm" variant="secondary">
                    Open in Trade Calculator
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}
      {!result && !running ? (
        <EmptyState
          title="Package Builder ready"
          description="Pick what you want back and what you will give, then build."
        />
      ) : null}
    </section>
  );
}
