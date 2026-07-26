/**
 * CollapsiblePanel — <Panel> that owns its own folded state.
 *
 * This exists to keep `Panel` itself hook-free. Panel is THE container
 * primitive, so it is the component most likely to be rendered from a
 * React Server Component: `/league`'s `shared-server.jsx::Card` is
 * rendered by seven RSCs today and is slated to become a Panel. Neither
 * module carries a "use client" directive, so both adopt their
 * importer's environment — and a single useState in Panel would turn
 * every one of those server consumers into a render-time crash.
 *
 * So the state lives here, below an explicit client boundary, and Panel
 * stays a pure function of its props. Panel keeps the *rendering* of the
 * disclosure (controlled via `collapsible` / `collapsed` /
 * `onToggleCollapsed` / `bodyId`) — only the state moved.
 *
 * Usage:
 *   <CollapsiblePanel title="Scouting" defaultCollapsed>
 *     …long diagnostics…
 *   </CollapsiblePanel>
 *
 * Props: everything <Panel> takes, plus
 *   defaultCollapsed boolean — initial folded state (default false)
 *
 * Requires a `title`, same as Panel's disclosure: a control with no
 * label is unusable, so it no-ops into a plain Panel without one.
 */
"use client";

import React, { useCallback, useId, useState } from "react";
import { Panel } from "./Panel";

export function CollapsiblePanel({ defaultCollapsed = false, ...props }) {
  const [collapsed, setCollapsed] = useState(Boolean(defaultCollapsed));
  const bodyId = useId();
  const toggle = useCallback(() => setCollapsed((v) => !v), []);

  return (
    <Panel
      {...props}
      collapsible
      collapsed={collapsed}
      onToggleCollapsed={toggle}
      bodyId={bodyId}
    />
  );
}
