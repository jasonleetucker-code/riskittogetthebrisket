/**
 * FileDropzone — pick (click + keyboard), drop and paste all hand files to
 * onFiles; the button is a real, described <button>.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileDropzone } from "@/components/ds";
import { clipboardImageFiles } from "@/components/ds/FileDropzone";

const png = (name = "shot.png") =>
  new File([new Uint8Array([0x89, 0x50])], name, { type: "image/png" });

function setup(props = {}) {
  const onFiles = vi.fn();
  const utils = render(
    <FileDropzone
      label="Choose screenshots"
      help="PNG, JPEG or WebP."
      multiple
      maxFiles={2}
      onFiles={onFiles}
      {...props}
    />,
  );
  const button = screen.getByRole("button", { name: "Choose screenshots" });
  const input = utils.container.querySelector('input[type="file"]');
  return { onFiles, button, input, ...utils };
}

describe("FileDropzone", () => {
  it("is a real button described by the help text, backed by a hidden image input", () => {
    const { button, input } = setup();
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAccessibleDescription("PNG, JPEG or WebP.");
    expect(input).toHaveAttribute("accept", "image/png,image/jpeg,image/webp");
    expect(input).toHaveAttribute("multiple");
    expect(input).toHaveAttribute("tabindex", "-1");
  });

  it("clicking the button opens the file input", async () => {
    const { button, input } = setup();
    const click = vi.spyOn(input, "click");
    await userEvent.click(button);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("Enter and Space on the focused button open the file input", async () => {
    const user = userEvent.setup();
    const { button, input } = setup();
    const click = vi.spyOn(input, "click");
    button.focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("chosen files reach onFiles, capped at maxFiles", async () => {
    const { input, onFiles } = setup();
    await userEvent.upload(input, [png("a.png"), png("b.png"), png("c.png")]);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0][0].map((f) => f.name)).toEqual([
      "a.png",
      "b.png",
    ]);
  });

  it("dropping files shows the active state while dragging and delivers them", () => {
    const { container, onFiles } = setup();
    const zone = container.querySelector(".ds-dropzone");
    const dataTransfer = {
      types: ["Files"],
      files: [png("drop.png")],
      dropEffect: "none",
    };
    fireEvent.dragEnter(zone, { dataTransfer });
    expect(zone).toHaveClass("ds-dropzone--active");
    const drop = createEvent.drop(zone, { dataTransfer });
    fireEvent(zone, drop);
    expect(drop.defaultPrevented).toBe(true);
    expect(zone).not.toHaveClass("ds-dropzone--active");
    expect(onFiles.mock.calls[0][0].map((f) => f.name)).toEqual(["drop.png"]);
  });

  it("pasting an image anywhere delivers it; a text paste is left alone", () => {
    const { onFiles } = setup();
    const file = png("pasted.png");
    const imagePaste = new Event("paste", { bubbles: true, cancelable: true });
    imagePaste.clipboardData = {
      items: [{ kind: "file", type: "image/png", getAsFile: () => file }],
      files: [],
    };
    window.dispatchEvent(imagePaste);
    expect(onFiles).toHaveBeenCalledWith([file]);
    expect(imagePaste.defaultPrevented).toBe(true);

    const textPaste = new Event("paste", { bubbles: true, cancelable: true });
    textPaste.clipboardData = {
      items: [{ kind: "string", type: "text/plain" }],
      files: [],
    };
    window.dispatchEvent(textPaste);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(textPaste.defaultPrevented).toBe(false);
  });

  it("disabled: no picking, dropping or pasting", () => {
    const { button, container, onFiles } = setup({ disabled: true });
    expect(button).toBeDisabled();
    const zone = container.querySelector(".ds-dropzone");
    fireEvent.drop(zone, {
      dataTransfer: { types: ["Files"], files: [png()] },
    });
    const paste = new Event("paste");
    paste.clipboardData = {
      items: [{ kind: "file", type: "image/png", getAsFile: () => png() }],
    };
    window.dispatchEvent(paste);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("single mode delivers one file", async () => {
    const { input, onFiles } = setup({ multiple: false, maxFiles: undefined });
    await userEvent.upload(input, [png("a.png")]);
    expect(onFiles.mock.calls[0][0]).toHaveLength(1);
  });

  it("clipboardImageFiles falls back to clipboardData.files", () => {
    const f = png();
    expect(clipboardImageFiles({ items: [], files: [f] })).toEqual([f]);
    expect(clipboardImageFiles(null)).toEqual([]);
  });
});
