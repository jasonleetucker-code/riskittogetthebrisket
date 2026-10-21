"use client";

// The asset picker's container: a bottom sheet on phones (the ds Drawer
// re-anchored to the bottom edge, the same documented override /trade's
// builder sheet uses) and a Modal from 768px.  Lazy: it loads on the first
// "Add player or pick" tap.  The sheet stays open between additions.

import { useEffect, useState } from "react";
import { Drawer, Modal } from "@/components/ds/Dialog";
import { Button } from "@/components/ds/Button";
import { teamLabel } from "@/lib/trade-advisor";
import { AdvisorAssetPicker } from "./_advisor-asset-picker.jsx";
import styles from "./trade-advisor.module.css";

const WIDE = "(min-width: 768px)";

function useWide() {
  const [wide, setWide] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(WIDE).matches : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const mq = window.matchMedia(WIDE);
    const on = () => setWide(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return wide;
}

export default function AdvisorAssetSheet({ team, isYou, entry, inTrade, onAdd, onRetry, onClose }) {
  const wide = useWide();
  const name = teamLabel(team);
  const title = isYou ? "Add from your team" : `Add from ${name}`;
  const Shell = wide ? Modal : Drawer;
  return (
    <Shell
      open
      onClose={onClose}
      title={title}
      className={wide ? "" : styles.sheet}
      closeLabel="Close the player and pick list"
    >
      <div className={styles.picker} data-testid="advisor-asset-sheet">
        <AdvisorAssetPicker teamName={name} entry={entry} inTrade={inTrade} onAdd={onAdd} onRetry={onRetry} />
        <Button variant="primary" className={styles.sheetDone} onClick={onClose}>
          Done
        </Button>
      </div>
    </Shell>
  );
}
