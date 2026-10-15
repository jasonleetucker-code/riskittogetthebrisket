/**
 * FileDropzone — the one file-intake primitive: pick, drop or paste.
 *
 * Usage:
 *   <FileDropzone
 *     label="Choose screenshots"
 *     help="PNG, JPEG or WebP. Drop files here or paste an image."
 *     multiple
 *     maxFiles={4}
 *     onFiles={(files) => ...}
 *   />
 *
 * Props:
 *   onFiles   (File[]) => void — required; receives at most maxFiles files
 *   accept    input accept list (default "image/png,image/jpeg,image/webp")
 *   multiple  boolean (false) — allow more than one file per pick/drop
 *   maxFiles  number — cap per pick/drop/paste (1 when !multiple)
 *   disabled  boolean — no picking, dropping or pasting
 *   label     button text (default "Choose files")
 *   help      guidance text, wired to the button via aria-describedby
 *   pasteTarget  "window" (default) | "none" — listen for clipboard images
 *               on window while mounted; "none" opts out
 *
 * Behaviour/a11y:
 *   - the control is a real <button> (Enter/Space, focus ring) that opens a
 *     visually hidden <input type="file">; on iOS that input offers the photo
 *     library, camera and Files.
 *   - dragging files over the zone shows an active state; dropping hands
 *     the files to onFiles.  Copy/paste of an image works while mounted.
 *   - the component never reads, validates or uploads file CONTENTS — the
 *     consumer decides what is acceptable (e.g. lib/image-downscale).
 */
"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";

const DEFAULT_ACCEPT = "image/png,image/jpeg,image/webp";

function capFiles(list, multiple, maxFiles) {
  const files = Array.from(list || []).filter(Boolean);
  const cap = multiple
    ? Number.isFinite(maxFiles) && maxFiles > 0
      ? maxFiles
      : files.length
    : 1;
  return files.slice(0, cap);
}

/** Image files on a clipboard event (items first, files as a fallback). */
export function clipboardImageFiles(clipboardData) {
  if (!clipboardData) return [];
  const out = [];
  for (const item of Array.from(clipboardData.items || [])) {
    if (
      item &&
      item.kind === "file" &&
      String(item.type || "").startsWith("image/")
    ) {
      const f = item.getAsFile?.();
      if (f) out.push(f);
    }
  }
  if (out.length) return out;
  return Array.from(clipboardData.files || []).filter((f) =>
    String(f?.type || "").startsWith("image/"),
  );
}

export function FileDropzone({
  onFiles,
  accept = DEFAULT_ACCEPT,
  multiple = false,
  maxFiles,
  disabled = false,
  label = "Choose files",
  help,
  pasteTarget = "window",
  className = "",
}) {
  const inputRef = useRef(null);
  const depthRef = useRef(0);
  const [dragging, setDragging] = useState(false);
  const helpId = useId();

  // Hold the latest callback so the paste listener is not re-bound on
  // every parent render.
  const onFilesRef = useRef(onFiles);
  useEffect(() => {
    onFilesRef.current = onFiles;
  }, [onFiles]);

  const deliver = (list) => {
    const files = capFiles(list, multiple, maxFiles);
    if (files.length) onFilesRef.current?.(files);
  };

  useEffect(() => {
    if (disabled || pasteTarget !== "window" || typeof window === "undefined")
      return undefined;
    const onPaste = (e) => {
      const files = clipboardImageFiles(e.clipboardData);
      if (!files.length) return; // a text paste belongs to whatever has focus
      e.preventDefault();
      const capped = capFiles(files, multiple, maxFiles);
      if (capped.length) onFilesRef.current?.(capped);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [disabled, pasteTarget, multiple, maxFiles]);

  const hasFiles = (e) =>
    Array.from(e.dataTransfer?.types || []).includes("Files");

  const onDragEnter = (e) => {
    if (disabled || !hasFiles(e)) return;
    e.preventDefault();
    depthRef.current += 1;
    setDragging(true);
  };
  const onDragOver = (e) => {
    if (disabled || !hasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  };
  const onDragLeave = () => {
    if (disabled) return;
    depthRef.current = Math.max(0, depthRef.current - 1);
    if (depthRef.current === 0) setDragging(false);
  };
  const onDrop = (e) => {
    if (disabled) return;
    e.preventDefault();
    depthRef.current = 0;
    setDragging(false);
    deliver(e.dataTransfer?.files);
  };

  const classes = [
    "ds-dropzone",
    dragging ? "ds-dropzone--active" : "",
    disabled ? "ds-dropzone--disabled" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={classes}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      data-dragging={dragging || undefined}
    >
      <Button
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        aria-describedby={help ? helpId : undefined}
        icon={<Icon name="arrow-up" size={14} />}
      >
        {label}
      </Button>
      {help ? (
        <p id={helpId} className="ds-dropzone__help">
          {help}
        </p>
      ) : null}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        className="ds-visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="ds-dropzone-input"
        onChange={(e) => {
          deliver(e.target.files);
          // Allow choosing the same file again (a retry after an error).
          e.target.value = "";
        }}
      />
    </div>
  );
}
