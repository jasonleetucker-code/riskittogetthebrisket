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
 * On error, renders a small fallback banner in place of the
 * crashed children, logs to console with a tagged prefix, and
 * continues rendering the rest of the page.  User can click
 * "Retry this section" to remount.
 */
import React from "react";


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
    if (this.state.error) {
      // Custom fallback if provided.
      if (typeof this.props.fallback === "function") {
        return this.props.fallback({
          error: this.state.error,
          retry: this._retry,
          name: this.props.name,
        });
      }
      // Default fallback: compact banner.
      return (
        <div
          role="alert"
          style={{
            padding: "var(--space-md, 16px)",
            border: "1px dashed rgba(239, 68, 68, 0.4)",
            borderRadius: "var(--radius-md, 8px)",
            background: "rgba(239, 68, 68, 0.05)",
            color: "var(--subtext, #aaa)",
            fontSize: "0.85rem",
            margin: "8px 0",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4, color: "#f87171" }}>
            {this.props.name || "Section"} unavailable
          </div>
          <div style={{ marginBottom: 6 }}>
            This section hit an error and was hidden so the rest of
            the page keeps working.
          </div>
          <button
            type="button"
            onClick={this._retry}
            style={{
              padding: "4px 10px",
              fontSize: "0.72rem",
              background: "transparent",
              border: "1px solid rgba(255,255,255,0.15)",
              color: "var(--subtext)",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Retry this section
          </button>
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
