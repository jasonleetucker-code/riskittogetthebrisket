/**
 * Lightweight fixed-height virtualized list — no external dep.
 *
 * Intended for rankings / rosters tables where ~500 players need
 * to render.  Full rendering of 500 DOM rows with complex cells
 * chokes mobile Safari scrolling; virtualizing 20-30 rows at a
 * time restores 60fps.
 *
 * API is intentionally narrow — full tables still need special
 * handling (sticky header, keyboard nav).  Use this for simple
 * fixed-row-height lists where a row is a div, not a <tr>.
 *
 *   <VirtualList
 *     items={players}
 *     itemHeight={44}
 *     overscan={6}
 *     renderItem={(player, index) => <PlayerRow player={player} />}
 *     height={600}
 *   />
 *
 * For <table> virtualization, prefer `react-window` (heavier but
 * correct for tbody) — but for this app's rows (mostly flex
 * containers) this is enough.
 */
"use client";

import React, { useEffect, useRef, useState } from "react";


export default function VirtualList({
  items,
  itemHeight,
  renderItem,
  overscan = 4,
  height = 600,
  className,
  style = {},
  ariaLabel,
}) {
  const scrollRef = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    const onScroll = () => setScrollTop(el.scrollTop);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const itemCount = Array.isArray(items) ? items.length : 0;
  const totalHeight = itemCount * itemHeight;
  const viewportHeight = height;

  let startIndex = Math.floor(scrollTop / itemHeight) - overscan;
  let endIndex = Math.ceil((scrollTop + viewportHeight) / itemHeight) + overscan;
  startIndex = Math.max(0, startIndex);
  endIndex = Math.min(itemCount, endIndex);

  const visible = [];
  for (let i = startIndex; i < endIndex; i++) {
    visible.push({ item: items[i], index: i });
  }

  return (
    <div
      ref={scrollRef}
      className={className}
      style={{
        height: viewportHeight,
        overflowY: "auto",
        overflowX: "hidden",
        position: "relative",
        WebkitOverflowScrolling: "touch",
        ...style,
      }}
      role="list"
      aria-label={ariaLabel}
    >
      <div style={{ height: totalHeight, position: "relative" }}>
        {visible.map(({ item, index }) => (
          <div
            key={index}
            role="listitem"
            style={{
              position: "absolute",
              top: index * itemHeight,
              left: 0, right: 0,
              height: itemHeight,
            }}
          >
            {renderItem(item, index)}
          </div>
        ))}
      </div>
    </div>
  );
}
