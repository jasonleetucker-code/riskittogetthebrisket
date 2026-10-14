"use client";

/**
 * ResilientSection — a section-scoped React error boundary.
 *
 * Next.js App Router provides app/error.jsx as a PAGE-level
 * boundary (the whole page goes to an error screen).  For a
 * page with multiple independent sections (e.g., trade calc:
 * rankings + players + signals + MC panel), we want ONE
 * section's crash to NOT take down the rest of the page.
 *
 * Usage:
 *   <ResilientSection name="MC panel">
 *     <MonteCarloButton sides={sides} />
 *   </ResilientSection>
 *
 *   // Around a React.lazy section:
 *   <ResilientSection name="Trade suggestions" recovery="reload">
 *     <Suspense fallback={null}><LazyDesk /></Suspense>
 *   </ResilientSection>
 *
 * On error, renders a compact negative banner in place of the crashed
 * children, logs to console with a tagged prefix, and continues
 * rendering the rest of the page.
 *
 * The fallback is styled with the design system's own classes
 * (`ds-banner--negative`, `ds-btn--sm`) rather than by importing the
 * `Banner` / `Button` components: this boundary is EAGER on /league
 * (LeagueClient) and /trade, and importing those components (plus
 * Banner's Icon) pulled ~3.2 KB into /league's first-load page chunk —
 * measured — for markup that only exists on the error path.
 *
 * Recovery — "Retry this section" or "Reload page":
 *
 *   - "retry" (default) remounts the children.  Right for a render
 *     crash that may not recur.
 *   - "reload" reloads the page.  REQUIRED around a React.lazy section:
 *     React.lazy caches a rejected import, so remounting re-throws the
 *     same failure forever.  The realistic failure is a deploy:
 *     deploy/deploy.sh swaps `.next` and deletes the old build, so a tab
 *     opened before the deploy 404s on its old chunk hashes the first
 *     time it asks for an on-demand section.  Only a reload fetches the
 *     new build's chunk names.
 *
 * A webpack ChunkLoadError is recovered by reload whatever `recovery`
 * says — a remount cannot fix a missing chunk.
 */
import React from "react";

function isChunkLoadError(error) {
  return (
    error?.name === "ChunkLoadError" ||
    /Loading (CSS )?chunk [^ ]+ failed/i.test(String(error?.message || ""))
  );
}

function reloadPage() {
  window.location.reload();
}

export default class ResilientSection extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, errorInfo: null, tries: 0 };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    // Logs are picked up by the browser console + any
    // error-reporting service that listens on window.onerror.
    console.error(
      `[ResilientSection:${this.props.name || "unnamed"}] crash:`,
      error, errorInfo,
    );
  }

  _retry = () => {
    this.setState((s) => ({ error: null, errorInfo: null, tries: s.tries + 1 }));
  };

  render() {
    const { error } = this.state;
    if (error) {
      const reload =
        this.props.recovery === "reload" || isChunkLoadError(error);
      // Custom fallback if provided.
      if (typeof this.props.fallback === "function") {
        return this.props.fallback({
          error,
          retry: reload ? reloadPage : this._retry,
          reload,
          name: this.props.name,
        });
      }
      // Default fallback: the design system's negative banner.
      return (
        <div role="alert" className="ds-banner ds-banner--negative">
          <div className="ds-banner__body">
            <p className="ds-banner__title">{`${this.props.name || "Section"} unavailable`}</p>
            <p>
              {reload
                ? "This section could not be loaded — the site may have been updated since this page was opened. Reload to get the latest version; the rest of the page keeps working."
                : "This section hit an error and was hidden so the rest of the page keeps working."}
            </p>
            <div style={{ marginTop: "var(--space-2)" }}>
              <button
                type="button"
                className="ds-btn ds-btn--secondary ds-btn--sm"
                onClick={reload ? reloadPage : this._retry}
              >
                {reload ? "Reload page" : "Retry this section"}
              </button>
            </div>
          </div>
        </div>
      );
    }
    return (
      // Keyed on tries so a retry remounts children cleanly.
      <React.Fragment key={this.state.tries}>
        {this.props.children}
      </React.Fragment>
    );
  }
}
