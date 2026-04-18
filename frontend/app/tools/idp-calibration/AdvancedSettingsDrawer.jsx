"use client";

import { useEffect, useState } from "react";
import { MobileSheet } from "@/components/ui";

const DEFAULT_SEASONS = [2022, 2023, 2024, 2025];
const DEFAULT_BUCKETS = [
  [1, 6],
  [7, 12],
  [13, 24],
  [25, 36],
  [37, 60],
  [61, 100],
];
const DEFAULT_YEAR_WEIGHTS = { 2025: 0.4, 2024: 0.3, 2023: 0.2, 2022: 0.1 };

export default function AdvancedSettingsDrawer({
  isOpen,
  onClose,
  initial,
  onSave,
}) {
  const [seasons, setSeasons] = useState(DEFAULT_SEASONS);
  const [replacementMode, setReplacementMode] = useState("starter_plus_buffer");
  const [bufferPct, setBufferPct] = useState(0.15);
  const [manualRanks, setManualRanks] = useState({ DL: "", LB: "", DB: "" });
  const [blendIntrinsic, setBlendIntrinsic] = useState(0.75);
  const [yearWeights, setYearWeights] = useState(DEFAULT_YEAR_WEIGHTS);
  const [minBucketSize, setMinBucketSize] = useState(3);
  const [minGames, setMinGames] = useState(0);
  const [topN, setTopN] = useState("");
  const [bucketEdges, setBucketEdges] = useState(DEFAULT_BUCKETS);

  useEffect(() => {
    if (!initial) return;
    if (Array.isArray(initial.seasons)) setSeasons(initial.seasons);
    if (initial.replacement?.mode) setReplacementMode(initial.replacement.mode);
    if (initial.replacement?.buffer_pct != null) setBufferPct(initial.replacement.buffer_pct);
    if (initial.replacement?.manual && typeof initial.replacement.manual === "object") {
      setManualRanks((prev) => ({
        ...prev,
        ...Object.fromEntries(
          Object.entries(initial.replacement.manual).map(([k, v]) => [k, v == null ? "" : String(v)]),
        ),
      }));
    }
    if (initial.blend?.intrinsic != null) setBlendIntrinsic(initial.blend.intrinsic);
    if (initial.year_weights) setYearWeights(initial.year_weights);
    if (initial.min_bucket_size != null) setMinBucketSize(initial.min_bucket_size);
    if (initial.min_games != null) setMinGames(initial.min_games);
    // Explicit clear when incoming settings carry no top_n — otherwise a
    // value from a prior run would stick and silently re-enable the
    // universe filter on the next Apply.
    if (initial.top_n == null || initial.top_n === "" || initial.top_n === 0) {
      setTopN("");
    } else {
      setTopN(String(initial.top_n));
    }
    if (Array.isArray(initial.bucket_edges)) setBucketEdges(initial.bucket_edges);
  }, [initial]);

  function handleYearWeight(year, value) {
    const num = Number(value);
    setYearWeights((prev) => ({
      ...prev,
      [year]: Number.isFinite(num) ? num : 0,
    }));
  }

  function handleSubmit() {
    const manualPayload =
      replacementMode === "manual"
        ? Object.fromEntries(
            Object.entries(manualRanks)
              .map(([pos, raw]) => [pos, Number(raw)])
              .filter(([, n]) => Number.isFinite(n) && n > 0),
          )
        : {};
    const parsed = {
      seasons: seasons.map((s) => Number(s)).filter((n) => Number.isFinite(n)),
      replacement: {
        mode: replacementMode,
        buffer_pct: Number(bufferPct) || 0,
        manual: manualPayload,
      },
      blend: { intrinsic: Number(blendIntrinsic) || 0 },
      year_weights: yearWeights,
      min_bucket_size: Number(minBucketSize) || 3,
      min_games: Number(minGames) || 0,
      top_n: topN ? Number(topN) : null,
      bucket_edges: bucketEdges,
    };
    onSave?.(parsed);
    onClose?.();
  }

  function updateManualRank(position, value) {
    setManualRanks((prev) => ({ ...prev, [position]: value }));
  }

  function addBucket() {
    const last = bucketEdges[bucketEdges.length - 1] || [0, 0];
    setBucketEdges([...bucketEdges, [last[1] + 1, last[1] + 10]]);
  }

  function updateBucket(idx, which, value) {
    const copy = bucketEdges.map((edge) => [...edge]);
    copy[idx][which] = Number(value) || 0;
    setBucketEdges(copy);
  }

  function removeBucket(idx) {
    setBucketEdges(bucketEdges.filter((_, i) => i !== idx));
  }

  return (
    <MobileSheet isOpen={isOpen} onClose={onClose} title="Advanced settings">
      <div className="idp-lab-settings">
        <fieldset className="idp-lab-fieldset">
          <legend>Seasons</legend>
          <input
            className="input"
            value={seasons.join(", ")}
            onChange={(e) =>
              setSeasons(
                e.target.value
                  .split(/[,\s]+/)
                  .filter(Boolean)
                  .map((v) => Number(v))
                  .filter((n) => Number.isFinite(n)),
              )
            }
          />
          <p className="muted text-sm">
            Comma-separated list. Default is 2022, 2023, 2024, 2025.
          </p>
        </fieldset>

        <fieldset className="idp-lab-fieldset">
          <legend>Replacement mode</legend>
          <select
            className="input"
            value={replacementMode}
            onChange={(e) => setReplacementMode(e.target.value)}
          >
            <option value="strict_starter">Strict starter cutoff</option>
            <option value="starter_plus_buffer">Starter plus buffer (default)</option>
            <option value="manual">Manual per-position rank</option>
          </select>
          {replacementMode === "starter_plus_buffer" && (
            <label className="idp-lab-field">
              <span className="idp-lab-label">Buffer % of team count</span>
              <input
                className="input"
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={bufferPct}
                onChange={(e) => setBufferPct(e.target.value)}
              />
            </label>
          )}
          {replacementMode === "manual" && (
            <>
              <p className="muted text-sm">
                Set the replacement rank per position. Leave blank to fall
                back to auto-derived cutoffs for that position.
              </p>
              {["DL", "LB", "DB"].map((pos) => (
                <label className="idp-lab-field" key={pos}>
                  <span className="idp-lab-label">
                    {pos} manual replacement rank
                  </span>
                  <input
                    className="input"
                    type="number"
                    min="1"
                    placeholder="e.g. 36"
                    value={manualRanks[pos] ?? ""}
                    onChange={(e) => updateManualRank(pos, e.target.value)}
                  />
                </label>
              ))}
            </>
          )}
        </fieldset>

        <fieldset className="idp-lab-fieldset">
          <legend>Blend weights</legend>
          <label className="idp-lab-field">
            <span className="idp-lab-label">
              Intrinsic weight ({blendIntrinsic}). Market = {(1 - blendIntrinsic).toFixed(2)}
            </span>
            <input
              className="input"
              type="range"
              step="0.05"
              min="0"
              max="1"
              value={blendIntrinsic}
              onChange={(e) => setBlendIntrinsic(Number(e.target.value))}
            />
          </label>
        </fieldset>

        <fieldset className="idp-lab-fieldset">
          <legend>Recency year weights</legend>
          {Object.keys(yearWeights)
            .sort()
            .map((year) => (
              <label className="idp-lab-field" key={year}>
                <span className="idp-lab-label">{year}</span>
                <input
                  className="input"
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={yearWeights[year]}
                  onChange={(e) => handleYearWeight(year, e.target.value)}
                />
              </label>
            ))}
          <p className="muted text-sm">
            Weights are renormalised across resolved seasons before aggregation.
          </p>
        </fieldset>

        <fieldset className="idp-lab-fieldset">
          <legend>Rank buckets</legend>
          {bucketEdges.map((edge, idx) => (
            <div className="idp-lab-bucket-row" key={idx}>
              <input
                className="input"
                type="number"
                value={edge[0]}
                onChange={(e) => updateBucket(idx, 0, e.target.value)}
              />
              <span>to</span>
              <input
                className="input"
                type="number"
                value={edge[1]}
                onChange={(e) => updateBucket(idx, 1, e.target.value)}
              />
              <button
                type="button"
                className="button"
                onClick={() => removeBucket(idx)}
              >
                ×
              </button>
            </div>
          ))}
          <button type="button" className="button" onClick={addBucket}>
            Add bucket
          </button>
        </fieldset>

        <fieldset className="idp-lab-fieldset">
          <legend>Universe filters</legend>
          <label className="idp-lab-field">
            <span className="idp-lab-label">Minimum games</span>
            <input
              className="input"
              type="number"
              min="0"
              value={minGames}
              onChange={(e) => setMinGames(e.target.value)}
            />
          </label>
          <label className="idp-lab-field">
            <span className="idp-lab-label">Top-N per position (blank = all)</span>
            <input
              className="input"
              type="number"
              min="0"
              value={topN}
              onChange={(e) => setTopN(e.target.value)}
            />
          </label>
          <label className="idp-lab-field">
            <span className="idp-lab-label">Min bucket size (merges below this)</span>
            <input
              className="input"
              type="number"
              min="1"
              value={minBucketSize}
              onChange={(e) => setMinBucketSize(e.target.value)}
            />
          </label>
        </fieldset>

        <div className="idp-lab-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={handleSubmit}
          >
            Apply settings
          </button>
        </div>
      </div>
    </MobileSheet>
  );
}
