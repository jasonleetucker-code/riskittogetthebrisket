"use client";

// ── Chart 3: trade flow Sankey ────────────────────────────────────────
// "Who traded with whom" as an owner-to-owner flow diagram.
//
// Each trade's sides produce two edges: side A → side B (for everything
// A sent) and side B → side A (for everything B sent).  Edge width
// encodes the count of assets that flowed between the pair over the
// entire activity feed.  Owners are stacked on both the left and right
// columns so the same owner can appear on each side and flows are
// always left-to-right (simplifying rendering vs. a full circular
// chord diagram).
//
// This is a pragmatic simplified Sankey: one source column + one
// target column, no multi-step flows.  Good enough for "Owner A sent
// 3 assets to Owner B across the season."
//
// Input:
//   trades = [{ sides: [{ ownerId, displayName, receivedAssets: [...] }] }]
// ─────────────────────────────────────────────────────────────────────

import {
  CHART_COLORS,
  chartBox,
  categoricalColor,
  linearScale,
  formatNumber,
} from "../../lib/chart-primitives.js";

function buildFlows(trades) {
  // flows[sourceOwner][targetOwner] = count of assets flowing source → target
  const flows = new Map();
  const ownerNames = new Map();
  for (const t of trades || []) {
    const sides = Array.isArray(t?.sides) ? t.sides : [];
    if (sides.length < 2) continue;
    for (const side of sides) {
      if (side?.ownerId) ownerNames.set(side.ownerId, side.displayName || side.ownerId);
    }
    // Each side.receivedAssets came FROM the other side(s) TO this side.
    // For the 2-team case that's unambiguous; for 3+-team we attribute
    // each received asset uniformly to all *other* sides' owners.
    for (let i = 0; i < sides.length; i++) {
      const receiver = sides[i];
      const received = Array.isArray(receiver?.receivedAssets) ? receiver.receivedAssets : [];
      if (received.length === 0) continue;
      const senders = sides.filter((_, j) => j !== i).map((s) => s.ownerId).filter(Boolean);
      if (senders.length === 0 || !receiver?.ownerId) continue;
      const perSender = received.length / senders.length;
      for (const senderId of senders) {
        if (!flows.has(senderId)) flows.set(senderId, new Map());
        const row = flows.get(senderId);
        row.set(receiver.ownerId, (row.get(receiver.ownerId) || 0) + perSender);
      }
    }
  }
  return { flows, ownerNames };
}

export default function TradeFlowSankey({
  trades,
  width = 720,
  height = 420,
}) {
  const { flows, ownerNames } = buildFlows(trades);
  if (flows.size === 0) {
    return (
      <div className="chart-empty" style={{ padding: 12, color: CHART_COLORS.axisLabel }}>
        No trade activity in the snapshot.
      </div>
    );
  }

  const owners = Array.from(ownerNames.keys()).sort((a, b) =>
    (ownerNames.get(a) || "").localeCompare(ownerNames.get(b) || ""),
  );
  const ownerIndex = new Map(owners.map((o, i) => [o, i]));

  // Sum totals sent + received per owner for node sizing.
  const totalSent = new Map();
  const totalReceived = new Map();
  for (const [src, row] of flows.entries()) {
    for (const [dst, n] of row.entries()) {
      totalSent.set(src, (totalSent.get(src) || 0) + n);
      totalReceived.set(dst, (totalReceived.get(dst) || 0) + n);
    }
  }

  const box = chartBox({
    width,
    height,
    margin: { left: 120, right: 120, top: 16, bottom: 16 },
  });
  const nodeGap = 6;
  const nodeHeight = Math.max(8, (box.innerHeight - nodeGap * (owners.length - 1)) / owners.length);
  const nodeTop = (i) => i * (nodeHeight + nodeGap);

  const maxFlow = Math.max(
    ...Array.from(flows.values()).flatMap((row) => Array.from(row.values())),
    1,
  );
  const flowWidthScale = linearScale(0, maxFlow, 0, Math.max(2, nodeHeight));

  const flowPaths = [];
  for (const [src, row] of flows.entries()) {
    const si = ownerIndex.get(src);
    if (si === undefined) continue;
    for (const [dst, n] of row.entries()) {
      const di = ownerIndex.get(dst);
      if (di === undefined) continue;
      const fw = flowWidthScale(n);
      const y1 = nodeTop(si) + nodeHeight / 2;
      const y2 = nodeTop(di) + nodeHeight / 2;
      const midX = box.innerWidth / 2;
      const d = `M0,${y1} C${midX},${y1} ${midX},${y2} ${box.innerWidth},${y2}`;
      flowPaths.push({
        d,
        w: Math.max(1, fw),
        color: categoricalColor(si),
        label: `${ownerNames.get(src)} → ${ownerNames.get(dst)}: ${formatNumber(n, n < 1 ? 1 : 0)} assets`,
      });
    }
  }

  return (
    <svg
      viewBox={box.viewBox}
      width="100%"
      height={height}
      role="img"
      aria-label="Trade flow diagram between franchises"
    >
      <g transform={box.plotTransform}>
        {/* Flow ribbons first (below nodes). */}
        {flowPaths.map((f, i) => (
          <path
            key={i}
            d={f.d}
            stroke={f.color}
            strokeWidth={f.w}
            strokeOpacity={0.35}
            fill="none"
          >
            <title>{f.label}</title>
          </path>
        ))}

        {/* Left column nodes (source) */}
        {owners.map((o, i) => {
          const y0 = nodeTop(i);
          const sent = totalSent.get(o) || 0;
          return (
            <g key={`src-${o}`} transform={`translate(${-6}, 0)`}>
              <rect
                x={-10}
                y={y0}
                width={10}
                height={nodeHeight}
                fill={categoricalColor(i)}
                fillOpacity={0.9}
                rx={1}
              />
              <text
                x={-16}
                y={y0 + nodeHeight / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={10}
                fill={CHART_COLORS.axisLabel}
              >
                {ownerNames.get(o)} ({formatNumber(sent, sent < 1 ? 1 : 0)})
              </text>
            </g>
          );
        })}

        {/* Right column nodes (target) */}
        {owners.map((o, i) => {
          const y0 = nodeTop(i);
          const received = totalReceived.get(o) || 0;
          return (
            <g key={`dst-${o}`} transform={`translate(${box.innerWidth + 6}, 0)`}>
              <rect
                x={0}
                y={y0}
                width={10}
                height={nodeHeight}
                fill={categoricalColor(i)}
                fillOpacity={0.9}
                rx={1}
              />
              <text
                x={16}
                y={y0 + nodeHeight / 2}
                textAnchor="start"
                dominantBaseline="middle"
                fontSize={10}
                fill={CHART_COLORS.axisLabel}
              >
                {ownerNames.get(o)} ({formatNumber(received, received < 1 ? 1 : 0)})
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export { buildFlows };
