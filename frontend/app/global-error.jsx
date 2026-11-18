"use client";

import { useEffect } from "react";
import "./globals.css";
import { Button } from "@/components/ds/Button";
import { EmptyState } from "@/components/ds/EmptyState";

/**
 * Last-resort boundary: replaces the ROOT layout when the layout itself (or
 * the shell above every route boundary) throws.  Because it replaces the
 * layout it must render its own <html>/<body>; it imports the global
 * stylesheet so the design-system tokens still apply, but none of the app
 * shell, providers or fonts exist here, so it stays deliberately plain.
 *
 * Like app/error.jsx it never prints `error.message`; the opaque digest is
 * the only detail shown, for support reports.
 */
export default function GlobalError({ error, reset }) {
  useEffect(() => {
    console.error("[GlobalError] Root layout error:", error);
  }, [error]);

  const digest = typeof error?.digest === "string" ? error.digest.slice(0, 40) : "";

  return (
    <html lang="en">
      <body>
        <div className="main-shell" role="alert" style={{ paddingTop: 64 }}>
          <EmptyState
            title="Something went wrong"
            description="Chase Upside hit an unexpected problem loading this page. It is usually temporary - try again."
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
        </div>
      </body>
    </html>
  );
}
