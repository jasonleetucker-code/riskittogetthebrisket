"use client";

// Best Trade to Send Each Team (C7-BEST-TRADE) — one offer per opponent.
//
// Display only: qualification, ranking and every number come from
// POST /api/trade/best-offers.  Recommendation only — there is no send
// action; "Open in Trade Calculator" hands the package to /trade.

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  SegmentedControl,
  SkeletonTable,
} from "@/components/ds";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildShareUrl } from "@/lib/trade-share";
import {
  UNKNOWN,
  concentrationLine,
  fmtSignedInt,
  fmtSignedPct,
  lineupLine,
  mergeCards,
  summarizeCard,
} from "@/lib/best-offers";
import {
  emptyRefinement,
  loadRefinement,
  refinementKey,
  saveRefinement,
  toRequest,
  toggleExclude,
  toggleLock,
} from "@/lib/trade-refinement";
import {
  OutgoingRefinement,
  RefinementBar,
} from "@/components/trade/RefinementControls";
import styles from "./best-offers.module.css";

const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

function cardStorageKey(owner, leagueKey, myTeam, opponent) {
  return refinementKey({
    owner,
    leagueKey,
    surface: "best-offers",
    context: `${myTeam}|${opponent}`,
  });
}

function AssetLine({ assets, refine }) {
  return (
    <ul className={styles.assets}>
      {(assets || []).map((a, i) => (
        <li key={`${a.name}-${i}`} className={styles.asset}>
          <span className={styles.assetName}>{a.name}</span>
          <Badge tone="neutral">{a.position}</Badge>
          {refine ? (
            <OutgoingRefinement
              name={a.name}
              refinement={refine.refinement}
              onLock={refine.onLock}
              onExclude={refine.onExclude}
              disabled={refine.disabled}
            />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function OfferCard({ card, myTeam, refine, regenerating }) {
  const s = summarizeCard(card);
  const offer = card.offer;
  const calcUrl = useMemo(() => {
    if (!offer) return null;
    const asName = (a) => a.boardRowName || a.name;
    try {
      return buildShareUrl({
        sides: [
          { name: myTeam || "You", players: offer.send.map(asName) },
          { name: card.team, players: offer.receive.map(asName) },
        ],
      });
    } catch {
      return null;
    }
  }, [offer, myTeam, card.team]);

  return (
    <article
      className={styles.card}
      aria-labelledby={`offer-${card.team}`}
      aria-busy={regenerating}
    >
      <header className={styles.cardHead}>
        <h3 id={`offer-${card.team}`} className={styles.team}>
          {card.team}
        </h3>
        {card.posture ? <Badge tone="neutral">{card.posture}</Badge> : null}
        {s.qualified ? (
          <span className={styles.verdicts}>
            <span>
              You <strong>{fmtSignedInt(s.ourGap)}</strong>
            </span>
            <span className={styles.sep} aria-hidden="true">
              ·
            </span>
            <span>
              {s.calculator || UNKNOWN}: them{" "}
              <strong>{fmtSignedPct(s.theirMarginPct)}</strong>
            </span>
            {s.confidence ? (
              <Badge tone="outline">{s.confidence} confidence</Badge>
            ) : null}
          </span>
        ) : null}
      </header>

      {!s.qualified ? (
        <div className={styles.noResult}>
          <strong>{s.label}</strong>
          {s.detail ? <p>{s.detail}</p> : null}
        </div>
      ) : (
        <>
          <div className={styles.sides}>
            <div>
              <h4 className={styles.sideLabel}>You send</h4>
              <AssetLine assets={offer.send} refine={refine} />
            </div>
            <div>
              <h4 className={styles.sideLabel}>You receive</h4>
              <AssetLine assets={offer.receive} />
            </div>
          </div>
          <dl className={styles.why}>
            <dt>Why this helps you</dt>
            <dd>{offer.whyThisHelpsUs}</dd>
            <dt>Why they may accept</dt>
            <dd>{offer.whyTheyMayAccept}</dd>
          </dl>
          <ul className={styles.facts}>
            {lineupLine(offer.lineupImpact) ? (
              <li>{lineupLine(offer.lineupImpact)}</li>
            ) : null}
            {concentrationLine(offer) ? (
              <li>{concentrationLine(offer)}</li>
            ) : null}
            {(offer.externalAll || [])
              .filter((v) => v.coverage !== "complete")
              .map((v) => (
                <li key={v.calculator}>
                  {v.label}:{" "}
                  {v.coverage === "withheld"
                    ? "withheld as stale"
                    : "does not price every asset"}
                </li>
              ))}
            {(offer.caveats || []).map((c) => (
              <li key={c} className={styles.caveat}>
                {c}
              </li>
            ))}
          </ul>
          <footer className={styles.cardFoot}>
            <span className={styles.muted}>{s.packageSize}</span>
            {calcUrl ? (
              <Button as={Link} href={calcUrl} size="sm" variant="secondary">
                Open in Trade Calculator
              </Button>
            ) : null}
          </footer>
        </>
      )}
      {refine ? (
        <RefinementBar
          refinement={refine.refinement}
          onLock={refine.onLock}
          onExclude={refine.onExclude}
          onSkip={() => {}}
          onClear={refine.onClear}
          disabled={refine.disabled}
        />
      ) : null}
    </article>
  );
}

export default function BestOffersView({
  myTeam,
  leagueKey,
  ownerKey,
  opponentNames = [],
}) {
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [regenerating, setRegenerating] = useState(null);
  const [error, setError] = useState("");
  const [useTeamContext, setUseTeamContext] = useState(true);
  const [refinements, setRefinements] = useState({});
  const seq = useRef(0);

  useEffect(() => {
    setResult(null);
    setRefinements({});
  }, [myTeam, leagueKey]);

  function refinementFor(opp) {
    if (refinements[opp]) return refinements[opp];
    return loadRefinement(cardStorageKey(ownerKey, leagueKey, myTeam, opp));
  }

  async function request(body) {
    const res = await fetch("/api/trade/best-offers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(withValuationMode(body)),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok)
      throw new Error(data?.error || `Request failed (${res.status})`);
    return data;
  }

  async function runAll(teamContext = useTeamContext) {
    if (!myTeam) return;
    const mine = ++seq.current;
    setRunning(true);
    setError("");
    try {
      // Saved per-card refinements travel with the full scan, so a stored
      // LOCK / EXCLUDE is honoured from the first result.
      const opponents = opponentNames.length
        ? opponentNames
        : (result?.opponents || []).map((o) => o.team);
      const refinementByOpponent = {};
      for (const opp of opponents) {
        const r = refinementFor(opp);
        if (r.lock.length || r.exclude.length)
          refinementByOpponent[opp] = toRequest(r);
      }
      const data = await request({
        myTeam,
        leagueKey: leagueKey || undefined,
        useTeamContext: teamContext !== false,
        refinementByOpponent,
      });
      if (mine !== seq.current) return;
      setResult(data);
      const loaded = {};
      for (const o of data.opponents || [])
        loaded[o.team] = refinementFor(o.team);
      setRefinements(loaded);
    } catch (err) {
      if (mine === seq.current) setError(err?.message || "Request failed");
    } finally {
      if (mine === seq.current) setRunning(false);
    }
  }

  async function regenerate(opp, nextRefinement) {
    setRegenerating(opp);
    setError("");
    try {
      const data = await request({
        myTeam,
        leagueKey: leagueKey || undefined,
        useTeamContext,
        opponents: [opp],
        refinementByOpponent: { [opp]: toRequest(nextRefinement) },
      });
      setResult((prev) => mergeCards(prev, data));
    } catch (err) {
      setError(err?.message || "Request failed");
    } finally {
      setRegenerating(null);
    }
  }

  function applyRefinement(opp, next) {
    setRefinements((prev) => ({ ...prev, [opp]: next }));
    saveRefinement(cardStorageKey(ownerKey, leagueKey, myTeam, opp), next);
    void regenerate(opp, next);
  }

  const cards = result?.opponents || [];
  const qualified = cards.filter((c) => c.status === "qualified").length;

  return (
    <section
      className={`${styles.view} psi-editorial`}
      aria-label="Best offer by opponent"
    >
      <p className={styles.lede}>
        One offer per team: a clear win for you on the canonical board after the
        Value Adjustment, and even or better for them on KTC or IDP Trade
        Calculator, priced on every asset. Recommendations only — nothing is
        sent.
      </p>
      <div className={styles.controls}>
        <SegmentedControl
          label="Analysis mode"
          options={CONTEXT_OPTIONS}
          value={useTeamContext ? "team" : "asset"}
          onChange={(v) => {
            const next = v === "team";
            setUseTeamContext(next);
            if (result) void runAll(next);
          }}
        />
        <Button onClick={() => runAll()} disabled={running || !myTeam}>
          {running
            ? "Scanning every team…"
            : "Find the best offer for each team"}
        </Button>
      </div>
      {result?.rankingMethod ? (
        <p className={styles.muted}>
          Ranking: declared prior ({result.rankingMethod.status}); every factor
          is shown on each offer. Best opportunity first.
        </p>
      ) : null}
      {error ? <Banner tone="negative">{error}</Banner> : null}
      {running ? <SkeletonTable rows={4} /> : null}
      {!running && result ? (
        <p className={styles.count} role="status">
          {qualified} of {cards.length} teams have a qualifying offer.
        </p>
      ) : null}
      {!running && result && !cards.length ? (
        <EmptyState
          title="No opponents to scan"
          description="This league has no other rosters loaded."
        />
      ) : null}
      {!running && cards.length ? (
        <div className={styles.cards}>
          {cards.map((card) => (
            <OfferCard
              key={card.team}
              card={card}
              myTeam={myTeam}
              regenerating={regenerating === card.team}
              refine={{
                refinement: refinements[card.team] || emptyRefinement(),
                onLock: (name) =>
                  applyRefinement(
                    card.team,
                    toggleLock(
                      refinements[card.team] || emptyRefinement(),
                      name,
                    ),
                  ),
                onExclude: (name) =>
                  applyRefinement(
                    card.team,
                    toggleExclude(
                      refinements[card.team] || emptyRefinement(),
                      name,
                    ),
                  ),
                onClear: () => applyRefinement(card.team, emptyRefinement()),
                disabled: running || regenerating === card.team,
              }}
            />
          ))}
        </div>
      ) : null}
      {!result && !running ? (
        <EmptyState
          title="Best offers ready"
          description="Scan every opponent for the single offer you would want to send and they could rationally accept."
        />
      ) : null}
    </section>
  );
}
