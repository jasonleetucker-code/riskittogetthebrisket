"use client";

/**
 * "Save to Trade Desk" on a generated-trade card. Saving records the package
 * on the user's private desk with status Candidate; it never sends anything.
 */
import { useEffect, useState } from "react";
import { Button } from "@/components/ds";
import { deskErrorText, packageIdentity, saveToDesk } from "@/lib/trade-desk";

export default function SaveToDeskButton({ body, disabled }) {
  const [state, setState] = useState({ kind: "idle", text: "" });
  // A re-run or refine can render a DIFFERENT package in the same card slot;
  // "Saved" belongs to the package that was saved, never to the slot.
  const identity = packageIdentity(body);
  useEffect(() => {
    setState({ kind: "idle", text: "" });
  }, [identity]);
  const save = async () => {
    setState({ kind: "saving", text: "" });
    const res = await saveToDesk(body);
    if (res.ok) setState({ kind: "saved", text: "Saved to your Trade Desk" });
    else if (res.code === "duplicate")
      setState({ kind: "saved", text: deskErrorText("duplicate") });
    else setState({ kind: "error", text: deskErrorText(res.code) });
  };
  return (
    <span role="status" aria-live="polite">
      {state.kind === "saved" ? (
        <span>{state.text}</span>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          onClick={save}
          disabled={disabled || state.kind === "saving"}
        >
          {state.kind === "saving" ? "Saving…" : "Save to Trade Desk"}
        </Button>
      )}
      {state.kind === "error" ? <span> {state.text}</span> : null}
    </span>
  );
}
