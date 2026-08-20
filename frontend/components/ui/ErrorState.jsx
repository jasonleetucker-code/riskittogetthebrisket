"use client";

/**
 * ErrorState — shown when a fetch or operation fails.
 *
 * Props:
 *   message — error description
 *   retry   — optional () => void to retry
 *
 * NOT the primitive to reach for in new code: it takes only a message, so
 * it is structurally unable to distinguish "signed out" from "the backend
 * is down" from "there is nothing here yet".  `ds/FailureState` renders a
 * classified failure and is the one to use.  This stays for its remaining
 * caller and gains the live region it never had — an error nobody is told
 * about is not much of an error state.
 */
export default function ErrorState({ message = "Something went wrong.", retry }) {
  return (
    <div className="error-state" role="alert">
      <p className="error-state-message">{message}</p>
      {retry && (
        <button className="button" onClick={retry} style={{ marginTop: 10 }}>
          Retry
        </button>
      )}
    </div>
  );
}
