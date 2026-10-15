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
import { deskBodyFromOffer } from "@/lib/trade-desk";
import SaveToDeskButton from "@/components/trade/SaveToDeskButton";
import ManagerEvidence from "@/components/trade/ManagerEvidence";
import {
  UNKNOWN,
  fmtSignedInt,
  fmtSignedPct,
  lineupLine,
  verdictLines,
} from "@/lib/best-offers";
import {
  BUILDER_MODES,
  IMPROVE_POSITIONS,
  PACKAGE_POSITIONS,
  buildRequest,
  externalLine,
  modeRequestFields,
  noResultText,
  requestErrorText,
  resultCountText,
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
  const [mode, setMode] = useState("custom");
  const [sellAsset, setSellAsset] = useState("");
  const [improvePosition, setImprovePosition] = useState("");
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
    setSellAsset("");
    setTarget("");
    setOpponent("");
    setError("");
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

  const fields = modeRequestFields(mode, {
    target,
    opponent,
    outgoing,
    positions,
    sellAsset,
    improvePosition,
  });

  async function run(nextRefinement = refinement) {
    if (!myTeam || !fields.ready) return;
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
              target: fields.target,
              opponent: fields.opponent,
              outgoing: fields.outgoing,
              positions: fields.positions,
              perOpponent: fields.perOpponent,
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
      if (!res.ok) throw new Error(requestErrorText(data?.error));
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
      <SegmentedControl
        label="What do you want to do?"
        options={BUILDER_MODES}
        value={mode}
        onChange={(m) => {
          setMode(m);
          setResult(null);
        }}
      />
      <div className={styles.form}>
        {mode === "sell" ? (
          <Field label="Player to sell">
            <Select
              value={sellAsset}
              onChange={(e) => setSellAsset(e.target.value)}
            >
              <option value="">Choose a player</option>
              {myRoster.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        {mode === "improve" ? (
          <Field label="Position to improve">
            <Select
              value={improvePosition}
              onChange={(e) => setImprovePosition(e.target.value)}
            >
              <option value="">Choose a position</option>
              {IMPROVE_POSITIONS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}
        {mode === "acquire" || mode === "custom" ? (
          <Field
            label={
              mode === "acquire"
                ? "Player or pick you want"
                : "Player or pick you want (optional)"
            }
          >
            <Input
              list="package-builder-targets"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={mode === "acquire" ? "Search other rosters" : "Any"}
            />
          </Field>
        ) : null}
        <datalist id="package-builder-targets">
          {otherPlayers.map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
        {mode === "acquire" || mode === "custom" ? (
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
        ) : null}
        <Field label="Most assets per side (players + picks)">
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
      {mode === "custom" || mode === "sell" ? (
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
          <span className={styles.muted}>
            {positions.length ? "" : "(any)"}
          </span>
        </div>
      ) : null}
      {mode === "sell" ? null : (
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
      )}
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
        <Button
          onClick={() => run()}
          disabled={running || !myTeam || !fields.ready}
        >
          {running ? "Building packages…" : "Build packages"}
        </Button>
      </div>
      {!fields.ready ? <p className={styles.muted}>{fields.missing}</p> : null}
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
          {resultCountText(result)}
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
                  <span>{externalLine(pkg, fmtSignedPct)}</span>
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
                <SaveToDeskButton
                  body={deskBodyFromOffer(pkg, {
                    leagueKey,
                    myTeam,
                    opponent: pkg.opponent,
                    source: "package_builder",
                  })}
                  disabled={!leagueKey}
                />
                <ManagerEvidence
                  evidence={pkg.managerEvidence}
                  team={pkg.opponent}
                />
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
