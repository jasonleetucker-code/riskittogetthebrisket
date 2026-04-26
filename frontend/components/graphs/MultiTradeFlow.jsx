"use client";

import { useMemo } from "react";

import { effectiveValue } from "@/lib/trade-logic";

// Multi-team trade flow visualisation.
//
// 3+team trades get dense fast — the side cards each list outgoing
// + incoming assets, but the user has to mentally aggregate "what's
// flowing where" across N cards.  This SVG visual collapses the
// whole thing into a single picture: one node per side plus directed
// curves between sides whose stroke-width is proportional to the
// dollar-weighted volume flowing in that direction.
//
// Why a custom SVG and not a sankey lib?  We need exactly two
// behaviours: (a) variable-thickness curves between a small fixed
// node count, (b) styling that matches our existing palette.  No
// d3-sankey dependency for ~150 lines of layout math.

const NODE_HEIGHT = 36;
const NODE_GAP = 14;
const NODE_WIDTH = 120;
const SIDE_PADDING = 24;
const VIEWBOX_HEIGHT_PER_SIDE = NODE_HEIGHT + NODE_GAP;

const SIDE_COLOR = [
  "rgba(255, 199, 4, 0.85)", // gold
  "rgba(96, 165, 250, 0.85)", // blue
  "rgba(74, 222, 128, 0.85)", // green
  "rgba(248, 113, 113, 0.85)", // red
  "rgba(168, 162, 158, 0.85)", // stone
  "rgba(192, 132, 252, 0.85)", // purple
];

function colourFor(idx) {
  return SIDE_COLOR[idx % SIDE_COLOR.length];
}

export default function MultiTradeFlow({ sides, sideFlowAssets, valueMode, settings }) {
  // Build a per-pair flow matrix: flows[i][j] = sum of dollar value
  // flowing FROM side i TO side j (one direction at a time).  We
  // only care about positive flows so the loop ignores the diagonal
  // and zero-value entries.  Asset value uses ``effectiveValue`` so
  // pick-discount + value-mode are honoured the same way the rest
  // of the trade builder honours them.
  const flows = useMemo(() => {
    const n = sides.length;
    const out = Array.from({ length: n }, () => Array(n).fill(0));
    if (!Array.isArray(sideFlowAssets)) return out;
    sideFlowAssets.forEach((flow, i) => {
      for (const { asset, toSideIdx } of flow?.outgoing || []) {
        if (toSideIdx == null || toSideIdx === i) continue;
        if (toSideIdx < 0 || toSideIdx >= n) continue;
        const v = Math.max(0, effectiveValue(asset, valueMode, settings));
        out[i][toSideIdx] += v;
      }
    });
    return out;
  }, [sides, sideFlowAssets, valueMode, settings]);

  const totalFlow = useMemo(() => {
    let total = 0;
    for (const row of flows) for (const v of row) total += v;
    return total;
  }, [flows]);

  // Don't render anything for trades that have no actual flow yet.
  // The 2-team case is also rendered fine, but it's strictly less
  // useful than the existing meter so we let the host decide whether
  // to show this component (sides.length >= 3 is the typical gate).
  if (sides.length < 2 || totalFlow <= 0) return null;

  const n = sides.length;
  const height = SIDE_PADDING * 2 + n * NODE_HEIGHT + (n - 1) * NODE_GAP;
  const viewWidth = 480;
  const leftX = 24;
  const rightX = viewWidth - 24 - NODE_WIDTH;

  // Each side appears once on the left (giver) and once on the right
  // (receiver).  Curves connect the giver column to the receiver
  // column proportional to the dollar volume.  Flow strokes are
  // capped at 30 px to keep the chart readable when one trade
  // dominates total value.
  const maxStroke = 28;
  const minStroke = 1.5;

  function nodeY(idx) {
    return SIDE_PADDING + idx * (NODE_HEIGHT + NODE_GAP);
  }
  function linkPath(srcIdx, dstIdx) {
    const sx = leftX + NODE_WIDTH;
    const sy = nodeY(srcIdx) + NODE_HEIGHT / 2;
    const dx = rightX;
    const dy = nodeY(dstIdx) + NODE_HEIGHT / 2;
    const cx = (sx + dx) / 2;
    return `M ${sx},${sy} C ${cx},${sy} ${cx},${dy} ${dx},${dy}`;
  }

  return (
    <div
      className="card"
      style={{
        marginBottom: 10,
        padding: "10px 12px",
        overflowX: "auto",
      }}
    >
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
        Trade flow · stroke width = relative dollar volume
      </div>
      <svg
        role="img"
        aria-label="Multi-team trade flow visualization"
        viewBox={`0 0 ${viewWidth} ${height}`}
        style={{ width: "100%", height: "auto", maxHeight: 320 }}
      >
        {/* Connection paths.  Drawn first so node rectangles draw
            on top and the labels stay legible. */}
        {flows.map((row, srcIdx) =>
          row.map((volume, dstIdx) => {
            if (volume <= 0) return null;
            const widthRatio = volume / totalFlow;
            const stroke = Math.max(
              minStroke,
              Math.min(maxStroke, widthRatio * maxStroke * 2.4),
            );
            return (
              <g key={`flow-${srcIdx}-${dstIdx}`}>
                <path
                  d={linkPath(srcIdx, dstIdx)}
                  stroke={colourFor(srcIdx)}
                  strokeWidth={stroke}
                  strokeOpacity={0.55}
                  fill="none"
                />
                {/* Label the stronger flows so the user can read off
                    dollar amounts; tiny flows just inherit the colour
                    cue from the curve. */}
                {widthRatio >= 0.05 && (
                  <text
                    x={(leftX + NODE_WIDTH + rightX) / 2}
                    y={(nodeY(srcIdx) + nodeY(dstIdx) + NODE_HEIGHT) / 2}
                    fill="var(--text)"
                    fontSize="10"
                    fontFamily="var(--mono)"
                    textAnchor="middle"
                    style={{ pointerEvents: "none" }}
                  >
                    {Math.round(volume).toLocaleString()}
                  </text>
                )}
              </g>
            );
          }),
        )}

        {/* Giver column (left) + receiver column (right).  We render
            the same set of side names twice so the user can see
            both ends of every flow without having to follow the
            curve back to its origin node. */}
        {sides.map((side, i) => (
          <g key={`giver-${i}`}>
            <rect
              x={leftX}
              y={nodeY(i)}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={6}
              fill={colourFor(i)}
              fillOpacity={0.85}
            />
            <text
              x={leftX + 8}
              y={nodeY(i) + NODE_HEIGHT / 2 + 4}
              fill="#0c1a36"
              fontSize="12"
              fontWeight="700"
            >
              {side.label} sends →
            </text>
          </g>
        ))}
        {sides.map((side, i) => (
          <g key={`receiver-${i}`}>
            <rect
              x={rightX}
              y={nodeY(i)}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={6}
              fill={colourFor(i)}
              fillOpacity={0.55}
            />
            <text
              x={rightX + NODE_WIDTH - 8}
              y={nodeY(i) + NODE_HEIGHT / 2 + 4}
              fill="#0c1a36"
              fontSize="12"
              fontWeight="700"
              textAnchor="end"
            >
              ← {side.label} gets
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
