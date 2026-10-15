"use client";

/**
 * trade-screenshot-import.jsx — "Import trade from screenshot" (C3-IMPORT-IMAGE).
 *
 * Loaded on demand (React.lazy via `dyn` in ./page.jsx); it renders only
 * after the user chooses Import trade -> From screenshot.
 *
 * Flow: up to four screenshots -> each is downscaled in the browser
 * (lib/image-downscale) and read by the backend, ONE image per request, in
 * order -> the answers are joined onto board rows and merged
 * (lib/screenshot-import) -> the user reviews and fixes the result -> ONE
 * `onImport([rowsA, rowsB], mode)` call.  Cancel closes with no change to
 * the trade.
 *
 * Product rules carried here: screenshots supply asset identities and
 * sides only, never values; nothing is guessed (ambiguous -> the user
 * chooses, unrecognised -> shown with a search, noise -> "Ignored text");
 * sides are neutral Side A / Side B with Swap always visible, because the
 * left of a screenshot is not necessarily the user's team.  No trade math
 * lives here.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Drawer,
  EmptyState,
  FileDropzone,
  Icon,
  Input,
  Modal,
  Select,
} from "@/components/ds";
import { prepareScreenshot } from "@/lib/image-downscale";
import {
  UNASSIGNED,
  addItem,
  confirmCandidate,
  describeImportError,
  describeWarning,
  importReady,
  joinToBoard,
  mergeImages,
  moveItem,
  removeItem,
  reviewCounts,
  swapReviewSides,
  toImportedSides,
  undoMerge,
} from "@/lib/screenshot-import";
import { searchCalculatorAssets } from "@/lib/trade-logic";
import styles from "./trade-screenshot-import.module.css";

export const MAX_SCREENSHOTS = 4;
const SIDE_NAMES = ["Side A", "Side B"];
const PENDING_PHASES = new Set(["queued", "preparing", "reading"]);
const NARROW_QUERY = "(width < 768px)";

/** True below the 768px canonical breakpoint (Drawer instead of Modal). */
function useNarrowViewport() {
  const [narrow, setNarrow] = useState(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return false;
    return window.matchMedia(NARROW_QUERY).matches;
  });
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return undefined;
    const mql = window.matchMedia(NARROW_QUERY);
    const onChange = () => setNarrow(mql.matches);
    onChange();
    mql.addEventListener?.("change", onChange);
    return () => mql.removeEventListener?.("change", onChange);
  }, []);
  return narrow;
}

function assetMeta(row) {
  if (!row) return "";
  return [row.pos, row.team].filter(Boolean).join(" · ");
}

// ── asset search (fix a "Not found" item, or add a missed asset) ──────

function AssetSearch({ rows, label, onPick, onCancel }) {
  const [query, setQuery] = useState("");
  const results = useMemo(
    () =>
      query.trim()
        ? searchCalculatorAssets(rows, query, [], { boardLimit: 6 })
        : [],
    [rows, query],
  );
  return (
    <div className={styles.search}>
      <Input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onCancel?.();
          }
        }}
        placeholder="Search players and picks"
        aria-label={label}
        autoFocus
      />
      {query.trim() ? (
        results.length ? (
          <ul className={styles.searchResults} aria-label="Search results">
            {results.map((r) => (
              <li key={r.name}>
                <Button variant="ghost" size="sm" onClick={() => onPick(r)}>
                  {r.name}
                  {assetMeta(r) ? (
                    <span className={styles.meta}>{assetMeta(r)}</span>
                  ) : null}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.note}>
            No board asset matches “{query.trim()}”.
          </p>
        )
      ) : null}
    </div>
  );
}

// ── one review line ───────────────────────────────────────────────────

function StatusBadge({ item }) {
  if (item.status === "resolved") return <Badge tone="outline">Matched</Badge>;
  if (item.status === "needs_confirmation")
    return <Badge tone="warning">Confirm</Badge>;
  return <Badge tone="negative">Not found</Badge>;
}

function ReviewItem({ item, area, rows, dispatch }) {
  const [searching, setSearching] = useState(false);
  const rawText = item.raw || "";
  const subject = rawText ? `“${rawText}”` : item.row?.name || "this asset";
  // The text as read, beside the asset it matched — omitted only when the
  // two are identical (the matched name already says it).
  const showRaw = Boolean(rawText) && rawText !== item.row?.name;
  const moves =
    area === UNASSIGNED
      ? [
          { to: 0, label: "To Side A" },
          { to: 1, label: "To Side B" },
        ]
      : [
          {
            to: area === 0 ? 1 : 0,
            label: `Move to ${SIDE_NAMES[area === 0 ? 1 : 0]}`,
          },
          { to: UNASSIGNED, label: "Needs a side" },
        ];

  return (
    <li className={styles.item} data-status={item.status}>
      <div className={styles.itemMain}>
        <div className={styles.itemIdentity}>
          {showRaw ? <span className={styles.raw}>{rawText}</span> : null}
          {item.row ? (
            <>
              {showRaw ? (
                <Icon name="arrow-right" size={12} className={styles.arrow} />
              ) : null}
              <span className={styles.matched}>{item.row.name}</span>
              {assetMeta(item.row) ? (
                <span className={styles.meta}>{assetMeta(item.row)}</span>
              ) : null}
            </>
          ) : null}
          {item.manual ? (
            <span className={styles.meta}>added by you</span>
          ) : null}
        </div>
        <div className={styles.itemBadges}>
          <StatusBadge item={item} />
          {item.possibleOverlap ? (
            <Badge tone="info">Possible repeat</Badge>
          ) : null}
        </div>
      </div>

      {item.viaAlias && item.row ? (
        <p className={styles.note}>
          The board prices “{item.boardName}” as {item.row.name}.
        </p>
      ) : null}
      {item.possibleOverlap ? (
        <p className={styles.note}>
          This asset ends one screenshot and starts the next. If that is the
          same line scrolled twice, remove one copy.
        </p>
      ) : null}

      {item.status === "needs_confirmation" ? (
        <div className={styles.fix}>
          <Select
            aria-label={`Choose the asset for ${subject}`}
            value=""
            onChange={(e) => {
              const chosen = item.candidates[Number(e.target.value)];
              if (chosen)
                dispatch((s) => confirmCandidate(s, item.id, chosen.row));
            }}
          >
            <option value="" disabled>
              Which asset is this?
            </option>
            {item.candidates.map((c, i) => (
              <option key={`${c.row.name}-${i}`} value={i}>
                {[c.row.name, assetMeta(c.row)].filter(Boolean).join(" — ")}
              </option>
            ))}
          </Select>
        </div>
      ) : null}

      {item.status === "unresolved" ? (
        <div className={styles.fix}>
          <p className={styles.note}>
            {item.reason === "not_on_board"
              ? "Not on the current board."
              : "Couldn't match this text to a board asset."}{" "}
            Choose the right asset or remove it.
          </p>
          {item.suggestions.length ? (
            <div
              className={styles.suggestions}
              role="group"
              aria-label={`Suggestions for ${subject}`}
            >
              {item.suggestions.map((sg, i) => (
                <Button
                  key={`${sg.row.name}-${i}`}
                  size="sm"
                  onClick={() =>
                    dispatch((s) => confirmCandidate(s, item.id, sg.row))
                  }
                >
                  Use {sg.row.name}
                </Button>
              ))}
            </div>
          ) : null}
          {searching ? (
            <AssetSearch
              rows={rows}
              label={`Search the board for ${subject}`}
              onPick={(r) => {
                dispatch((s) => confirmCandidate(s, item.id, r));
                setSearching(false);
              }}
              onCancel={() => setSearching(false)}
            />
          ) : (
            <Button
              variant="ghost"
              size="sm"
              icon={<Icon name="search" size={12} />}
              onClick={() => setSearching(true)}
            >
              Find asset
            </Button>
          )}
        </div>
      ) : null}

      <div className={styles.itemActions}>
        {moves.map((m) => (
          <Button
            key={String(m.to)}
            variant="ghost"
            size="sm"
            onClick={() => dispatch((s) => moveItem(s, item.id, m.to))}
            aria-label={`${m.label}: ${item.row?.name || rawText || "asset"}`}
          >
            {m.label}
          </Button>
        ))}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => dispatch((s) => removeItem(s, item.id))}
          aria-label={`Remove ${item.row?.name || rawText || "asset"}`}
        >
          Remove
        </Button>
      </div>
    </li>
  );
}

// ── one side column ───────────────────────────────────────────────────

function SideColumn({ index, side, rows, dispatch }) {
  const [adding, setAdding] = useState(false);
  const headingId = `shot-side-${index}`;
  return (
    <section className={styles.column} aria-labelledby={headingId}>
      <header className={styles.columnHead}>
        <h3 id={headingId} className={styles.columnTitle}>
          {SIDE_NAMES[index]}
        </h3>
        <span className={styles.count}>
          {side.items.length} {side.items.length === 1 ? "asset" : "assets"}
        </span>
      </header>
      {side.labelSource === "anchor" && side.label ? (
        <p className={styles.note}>Screenshot label: “{side.label}”</p>
      ) : null}
      {side.items.length ? (
        <ul className={styles.list}>
          {side.items.map((it) => (
            <ReviewItem
              key={it.id}
              item={it}
              area={index}
              rows={rows}
              dispatch={dispatch}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.note}>No assets on this side.</p>
      )}
      {adding ? (
        <AssetSearch
          rows={rows}
          label={`Add an asset to ${SIDE_NAMES[index]}`}
          onPick={(r) => {
            dispatch((s) => addItem(s, index, r));
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : (
        <Button
          variant="ghost"
          size="sm"
          icon={<Icon name="search" size={12} />}
          onClick={() => setAdding(true)}
          aria-label={`Add missing asset to ${SIDE_NAMES[index]}`}
        >
          Add missing asset
        </Button>
      )}
    </section>
  );
}

// ── the dialog ────────────────────────────────────────────────────────

function phaseText(img) {
  switch (img.phase) {
    case "queued":
      return "Waiting…";
    case "preparing":
      return "Preparing…";
    case "reading":
      return "Reading…";
    case "done": {
      const n =
        (img.response?.sides || []).reduce(
          (acc, s) => acc + (s?.items?.length || 0),
          0,
        ) + (img.response?.unassigned?.length || 0);
      return `Read — ${n} ${n === 1 ? "asset" : "assets"} found`;
    }
    default:
      return img.error?.message || "Couldn't read this screenshot.";
  }
}

async function readOneScreenshot(dataUrl, index, signal) {
  let res;
  try {
    res = await fetch("/api/trade/import-screenshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: dataUrl, index }),
      cache: "no-store",
      signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    return { error: describeImportError(0, null) };
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.ok === false) {
    return {
      error: describeImportError(
        res.status,
        data,
        res.headers?.get?.("Retry-After") || null,
      ),
    };
  }
  return { data };
}

let imageSeq = 0;

export function ScreenshotImportDialog({
  onClose,
  onImport,
  hasExistingAssets = false,
  rows = [],
  rowByName,
  rowByLowerName,
  pickAliases,
  status: statusProp = null,
}) {
  const narrow = useNarrowViewport();
  const [status, setStatus] = useState(statusProp);
  const [images, setImages] = useState([]);
  const [review, setReview] = useState(null);
  const imagesRef = useRef(images);
  imagesRef.current = images;
  const busyRef = useRef(false);
  const abortRef = useRef(null);
  const [tick, setTick] = useState(0);

  // Board lookups for the join, held in a ref so a background board refresh
  // never silently rebuilds (and discards) a review the user is editing.
  const rowsByPlayerId = useMemo(() => {
    const m = new Map();
    for (const r of rows || []) {
      if (!r?.playerId) continue;
      const key = String(r.playerId);
      if (!m.has(key)) m.set(key, []);
      m.get(key).push(r);
    }
    return m;
  }, [rows]);
  const mapsRef = useRef(null);
  mapsRef.current = { rowByName, rowByLowerName, pickAliases, rowsByPlayerId };

  // (a) Status: reuse the page's answer when it has one, else ask once.
  useEffect(() => {
    if (statusProp) return undefined;
    let alive = true;
    fetch("/api/trade/import-screenshot/status", { cache: "no-store" })
      .then((r) => r.json().catch(() => ({})))
      .then((d) => {
        if (alive)
          setStatus(
            d && typeof d === "object"
              ? d
              : { available: false, enabled: false },
          );
      })
      .catch(() => {
        if (alive)
          setStatus({
            available: false,
            enabled: false,
            reason: "unreachable",
          });
      });
    return () => {
      alive = false;
    };
  }, [statusProp]);

  // Abort an in-flight read and drop previews when the dialog goes away.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      for (const img of imagesRef.current) {
        if (img.previewUrl) URL.revokeObjectURL?.(img.previewUrl);
      }
    },
    [],
  );

  const patchImage = useCallback((key, patch) => {
    setImages((prev) =>
      prev.map((im) => (im.key === key ? { ...im, ...patch } : im)),
    );
  }, []);

  // (b) Sequential reads — one image per request, in upload order.
  const runOne = useCallback(
    async (key) => {
      const img = imagesRef.current.find((im) => im.key === key);
      if (!img) return;
      let dataUrl = img.dataUrl;
      if (!dataUrl) {
        patchImage(key, { phase: "preparing", error: null });
        try {
          dataUrl = (await prepareScreenshot(img.file)).dataUrl;
        } catch (err) {
          patchImage(key, {
            phase: "error",
            error: {
              code: err?.code || "prepare_failed",
              retryable: false,
              message: err?.message || "That image could not be opened.",
            },
          });
          return;
        }
      }
      patchImage(key, { phase: "reading", dataUrl, error: null });
      const index = Math.max(
        0,
        imagesRef.current.findIndex((im) => im.key === key),
      );
      const ctl = new AbortController();
      abortRef.current = ctl;
      try {
        const { data, error } = await readOneScreenshot(
          dataUrl,
          index,
          ctl.signal,
        );
        if (error) patchImage(key, { phase: "error", error });
        else
          patchImage(key, {
            phase: "done",
            response: data,
            error: null,
            version: Date.now(),
          });
      } catch {
        // aborted: the dialog closed
      } finally {
        if (abortRef.current === ctl) abortRef.current = null;
      }
    },
    [patchImage],
  );

  useEffect(() => {
    if (busyRef.current) return;
    const next = images.find((im) => im.phase === "queued");
    if (!next) return;
    busyRef.current = true;
    runOne(next.key).finally(() => {
      busyRef.current = false;
      setTick((t) => t + 1);
    });
  }, [images, tick, runOne]);

  // Rebuild the review once nothing is still being read.
  const pending = images.some((im) => PENDING_PHASES.has(im.phase));
  const doneSignature = images
    .map((im) => (im.phase === "done" ? `${im.key}:${im.version}` : "-"))
    .join("|");
  useEffect(() => {
    if (pending) return;
    const perImage = imagesRef.current
      .map((im, pos) =>
        im.phase === "done"
          ? joinToBoard({ ...im.response, imageIndex: pos }, mapsRef.current)
          : null,
      )
      .filter(Boolean);
    setReview(perImage.length ? mergeImages(perImage) : null);
  }, [pending, doneSignature]);

  const addFiles = (files) => {
    setImages((prev) => {
      const room = MAX_SCREENSHOTS - prev.length;
      const added = files.slice(0, Math.max(0, room)).map((file) => ({
        key: `shot-${(imageSeq += 1)}`,
        file,
        name: file.name || "screenshot",
        previewUrl:
          typeof URL !== "undefined" &&
          typeof URL.createObjectURL === "function"
            ? URL.createObjectURL(file)
            : null,
        phase: "queued",
        dataUrl: null,
        response: null,
        error: null,
        version: 0,
      }));
      return [...prev, ...added];
    });
  };

  const removeImage = (key) => {
    setImages((prev) => {
      const gone = prev.find((im) => im.key === key);
      if (gone?.previewUrl) URL.revokeObjectURL?.(gone.previewUrl);
      return prev.filter((im) => im.key !== key);
    });
  };

  const retryImage = (key) => patchImage(key, { phase: "queued", error: null });

  const dispatch = useCallback((fn) => setReview((s) => (s ? fn(s) : s)), []);

  const enabled = status ? status.enabled !== false : true;
  const available = status ? Boolean(status.available) && enabled : false;
  const ready = importReady(review);
  const counts = review ? reviewCounts(review) : null;
  const blockers = counts
    ? [
        counts.needsConfirmation ? `confirm ${counts.needsConfirmation}` : null,
        counts.unresolved ? `fix ${counts.unresolved} not found` : null,
        counts.unassigned ? `place ${counts.unassigned} in a side` : null,
        counts.assets === 0 ? "add at least one asset" : null,
      ].filter(Boolean)
    : [];

  const doImport = (mode) => {
    if (!ready || !review) return;
    onImport(toImportedSides(review), mode);
  };

  const Dialog = narrow ? Drawer : Modal;
  const statusLoading = !status;

  return (
    <Dialog
      open
      onClose={onClose}
      title="Import trade from screenshot"
      className={narrow ? undefined : styles.dialogWide}
    >
      <div className={styles.body} data-testid="screenshot-import">
        <p className={styles.lede}>
          Screenshots supply the assets and sides only — every value comes from
          the board. Nothing changes until you import.
        </p>

        {!statusLoading && !enabled ? (
          <Banner tone="info" title="Screenshot import is turned off">
            Use Import trade → From KeepTradeCut URL, or add assets by hand.
          </Banner>
        ) : null}
        {!statusLoading && enabled && !available ? (
          <Banner tone="warning" title="Screenshot reading isn't set up yet">
            The server can't read screenshots right now
            {status?.reason ? ` (${status.reason})` : ""}. You can still build
            the trade by hand or import a KeepTradeCut URL.
          </Banner>
        ) : null}

        <FileDropzone
          label={images.length ? "Add screenshots" : "Choose screenshots"}
          help={`PNG, JPEG or WebP, up to ${MAX_SCREENSHOTS}. Drop files here or paste an image. Adding or re-reading a screenshot rebuilds the review.`}
          multiple
          maxFiles={Math.max(1, MAX_SCREENSHOTS - images.length)}
          disabled={
            statusLoading || !available || images.length >= MAX_SCREENSHOTS
          }
          onFiles={addFiles}
        />

        {images.length ? (
          <ol className={styles.images} aria-label="Screenshots">
            {images.map((img, pos) => (
              <li key={img.key} className={styles.image} data-phase={img.phase}>
                {img.previewUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    className={styles.thumb}
                    src={img.previewUrl}
                    alt={`Screenshot ${pos + 1}`}
                  />
                ) : null}
                <div className={styles.imageInfo}>
                  <span className={styles.imageName}>Screenshot {pos + 1}</span>
                  <span
                    className={
                      img.phase === "error" ? styles.imageError : styles.meta
                    }
                    role={img.phase === "error" ? "alert" : undefined}
                  >
                    {phaseText(img)}
                  </span>
                </div>
                <div className={styles.imageActions}>
                  {(img.phase === "error" && img.error?.retryable) ||
                  img.phase === "done" ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => retryImage(img.key)}
                      aria-label={`Retry screenshot ${pos + 1}`}
                    >
                      Retry
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={
                      PENDING_PHASES.has(img.phase) && img.phase !== "queued"
                    }
                    onClick={() => removeImage(img.key)}
                    aria-label={`Remove screenshot ${pos + 1}`}
                  >
                    Remove
                  </Button>
                </div>
              </li>
            ))}
          </ol>
        ) : null}

        {pending ? (
          <p className={styles.note} role="status">
            Reading screenshots…
          </p>
        ) : null}

        {review && !pending ? (
          <div className={styles.review}>
            {review.warnings.map((w, i) => (
              <Banner key={`${w.code}-${w.sourceImage}-${i}`} tone="warning">
                {describeWarning(w, images.length)}
              </Banner>
            ))}
            {review.mergeNotes.map((note, i) => (
              <Banner
                key={`merge-${note.sourceImage}-${note.side}`}
                tone="info"
              >
                <span>
                  Screenshots {note.sourceImage} and {note.sourceImage + 1}{" "}
                  overlapped: {note.count} repeated assets on{" "}
                  {SIDE_NAMES[note.side]} were kept once.
                </span>{" "}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => dispatch((s) => undoMerge(s, i))}
                >
                  Undo
                </Button>
              </Banner>
            ))}

            <div className={styles.reviewBar}>
              <h3 className={styles.reviewTitle}>Review</h3>
              <Button
                size="sm"
                icon={<Icon name="swap" size={12} />}
                onClick={() => dispatch(swapReviewSides)}
              >
                Swap sides
              </Button>
            </div>

            {counts.assets === 0 && review.unassigned.length === 0 ? (
              <EmptyState
                title="No trade assets found"
                description="Try a tighter crop of the trade, or add the assets by hand below."
              />
            ) : null}

            <div className={styles.columns}>
              <SideColumn
                index={0}
                side={review.sides[0]}
                rows={rows}
                dispatch={dispatch}
              />
              <SideColumn
                index={1}
                side={review.sides[1]}
                rows={rows}
                dispatch={dispatch}
              />
            </div>

            {review.unassigned.length ? (
              <section className={styles.tray} aria-labelledby="shot-tray">
                <header className={styles.columnHead}>
                  <h3 id="shot-tray" className={styles.columnTitle}>
                    Needs a side
                  </h3>
                  <span className={styles.count}>
                    {review.unassigned.length}
                  </span>
                </header>
                <p className={styles.note}>
                  These assets were read but couldn&apos;t be placed on a side.
                </p>
                <ul className={styles.list}>
                  {review.unassigned.map((it) => (
                    <ReviewItem
                      key={it.id}
                      item={it}
                      area={UNASSIGNED}
                      rows={rows}
                      dispatch={dispatch}
                    />
                  ))}
                </ul>
              </section>
            ) : null}

            {review.ignored.length ? (
              <details className={styles.ignored}>
                <summary className={styles.ignoredSummary}>
                  Ignored text ({review.ignored.length})
                </summary>
                <ul className={styles.ignoredList}>
                  {review.ignored.map((g, i) => (
                    <li key={`${g.sourceImage}-${i}`}>
                      <span className={styles.raw}>{g.raw}</span>
                      {g.reason ? (
                        <span className={styles.meta}>
                          {g.reason.replace(/_/g, " ")}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}

        <footer className={styles.footer}>
          {review && !pending && !ready && blockers.length ? (
            <p className={styles.note} aria-live="polite">
              Before importing: {blockers.join(" · ")}.
            </p>
          ) : null}
          <div className={styles.actions}>
            <Button onClick={onClose}>Cancel</Button>
            {hasExistingAssets ? (
              <>
                <Button
                  onClick={() => doImport("add")}
                  disabled={!ready || pending}
                >
                  Add to current trade
                </Button>
                <Button
                  variant="primary"
                  onClick={() => doImport("replace")}
                  disabled={!ready || pending}
                >
                  Replace current trade
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                onClick={() => doImport("replace")}
                disabled={!ready || pending}
              >
                Import trade
              </Button>
            )}
          </div>
        </footer>
      </div>
    </Dialog>
  );
}
