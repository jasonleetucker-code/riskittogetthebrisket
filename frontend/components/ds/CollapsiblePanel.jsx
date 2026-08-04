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
 *   mountCollapsedChildren boolean — default TRUE, matching Panel, which
 *     renders the body and hides it with the `hidden` attribute. Set
 *     FALSE to skip rendering children until the panel is first opened.
 *
 * Why that second prop exists: `hidden` still MOUNTS the children, so a
 * `dynamic()` import inside a collapsed panel fetches its chunk
 * immediately and the split buys nothing. /trade's "Second opinions"
 * block is ~44 KB of charts behind `defaultCollapsed`, and the only way
 * to defer it is to not render it.
 *
 * Opt-in rather than the default because skipping the mount is a real
 * behaviour change: children never run their effects, never fetch, and
 * hold no state until first open. That is right for a panel of inert
 * read-only charts and wrong for anything that needs to be warm before
 * the user looks at it. Once opened the children stay mounted, so
 * toggling shut does not discard their state.
 *
 * Requires a `title`, same as Panel's disclosure: a control with no
 * label is unusable, so it no-ops into a plain Panel without one.
 */
"use client";

import React, { useCallback, useId, useState } from "react";
import { Panel } from "./Panel";

export function CollapsiblePanel({
  defaultCollapsed = false,
  mountCollapsedChildren = true,
  children,
  ...props
}) {
  const [collapsed, setCollapsed] = useState(Boolean(defaultCollapsed));
  const bodyId = useId();
  const toggle = useCallback(() => setCollapsed((v) => !v), []);
  // Latch: once opened, keep the children mounted so folding the panel
  // shut does not throw away their state or re-run their effects.
  const [everOpened, setEverOpened] = useState(!defaultCollapsed);
  if (!collapsed && !everOpened) setEverOpened(true);

  const showChildren = mountCollapsedChildren || everOpened;

  return (
    <Panel
      {...props}
      collapsible
      collapsed={collapsed}
      onToggleCollapsed={toggle}
      bodyId={bodyId}
    >
      {showChildren ? children : null}
    </Panel>
  );
}
