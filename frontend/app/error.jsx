"use client";

import { useEffect } from "react";
import { Button } from "@/components/ds/Button";
import { EmptyState } from "@/components/ds/EmptyState";

/**
 * Route-segment error boundary — catches an unhandled client-side exception
 * and renders a recovery UI instead of Next's generic crash page.
 *
 * What it must NOT do: print `error.message`.  A render exception's message is
 * an implementation detail (a stack-adjacent string, an internal field name,
 * on a server-component failure a fragment of a backend body) that gives the
 * reader nothing to act on and gives a stranger a free look at internals.  The
 * full error still goes to the browser console for debugging.
 *
 * The `digest` IS kept, as a short "Reference" line.  Next replaces a
 * server-side error's message with an opaque hash in production and logs the
 * real error against that same hash in the server log, so the digest is the
 * one safe handle a support report can carry.  It is not rendered when absent
 * (a purely client-side exception has none).
 *
 * Styling is the design-system EmptyState + Button — no inline colours.
 */
export default function RouteError({ error, reset }) {
  useEffect(() => {
    // Developer-facing only (browser console); never rendered.
    console.error("[RouteError] Unhandled client error:", error);
  }, [error]);

  const digest = typeof error?.digest === "string" ? error.digest.slice(0, 40) : "";

  return (
    <section className="main-shell" role="alert" style={{ paddingTop: 40 }}>
      <EmptyState
        title="Something went wrong"
        description="This page hit an unexpected problem. It is usually temporary - try again, or head back to the dashboard."
        action={
          <>
            <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              <Button variant="primary" onClick={() => reset()}>
                Try again
              </Button>
              <Button as="a" href="/" variant="secondary">
                Go home
              </Button>
            </div>
            {digest ? (
              <p
                className="ds-empty__description"
                data-testid="error-reference"
                style={{ fontSize: "0.85em" }}
              >
                Reference: {digest}
              </p>
            ) : null}
          </>
        }
      />
    </section>
  );
}
