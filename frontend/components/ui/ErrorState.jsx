"use client";

/**
 * ErrorState — shown when a fetch or operation fails.
 *
 * Props:
 *   message — error description
 *   retry   — optional () => void to retry
 */
export default function ErrorState({ message = "Something went wrong.", retry }) {
  return (
    <div className="error-state">
      <p className="error-state-message">{message}</p>
      {retry && (
        <button className="button" onClick={retry} style={{ marginTop: 10 }}>
          Retry
        </button>
      )}
    </div>
  );
}
