/**
 * lib/image-downscale — screenshot validation, downscale and re-encode.
 * No real codec: decode and canvas are injected.
 */
import { describe, expect, it, vi } from "vitest";
import {
  MAX_INPUT_BYTES,
  MAX_LONG_EDGE,
  MAX_UPLOAD_BYTES,
  ScreenshotPrepError,
  dataUrlByteLength,
  prepareScreenshot,
  scaledDimensions,
  sniffImageType,
  validateScreenshotFile,
} from "@/lib/image-downscale";

const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const JPEG_MAGIC = [0xff, 0xd8, 0xff, 0xe0];
const WEBP_MAGIC = [0x52, 0x49, 0x46, 0x46, 1, 2, 3, 4, 0x57, 0x45, 0x42, 0x50];
const GIF_MAGIC = [0x47, 0x49, 0x46, 0x38, 0x39, 0x61];

const blob = (magic, type, pad = 64) =>
  new Blob([new Uint8Array([...magic, ...new Array(pad).fill(0)])], { type });

/** A base64 data URL whose decoded payload is exactly ``bytes`` long. */
function dataUrlOf(bytes, mime = "image/png") {
  const b64Len = Math.ceil(bytes / 3) * 4;
  const pad = (3 - (bytes % 3)) % 3;
  return `data:${mime};base64,${"A".repeat(b64Len - pad)}${"=".repeat(pad)}`;
}

function fakeCanvas({ pngBytes, jpegBytes }) {
  const drawImage = vi.fn();
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage }),
    toDataURL: vi.fn((mime) =>
      mime === "image/jpeg"
        ? dataUrlOf(jpegBytes, "image/jpeg")
        : dataUrlOf(pngBytes),
    ),
  };
  const createCanvas = vi.fn((w, h) => {
    canvas.width = w;
    canvas.height = h;
    return canvas;
  });
  return { canvas, createCanvas, drawImage };
}

const decodeTo = (width, height) =>
  vi.fn(async () => ({ width, height, close: vi.fn() }));

describe("sniffImageType", () => {
  it("recognises PNG, JPEG and WebP magic numbers", () => {
    expect(sniffImageType(new Uint8Array(PNG_MAGIC))).toBe("image/png");
    expect(sniffImageType(new Uint8Array(JPEG_MAGIC))).toBe("image/jpeg");
    expect(sniffImageType(new Uint8Array(WEBP_MAGIC))).toBe("image/webp");
  });

  it("rejects anything else, including truncated headers", () => {
    expect(sniffImageType(new Uint8Array(GIF_MAGIC))).toBeNull();
    expect(sniffImageType(new Uint8Array([0x89, 0x50]))).toBeNull();
    expect(sniffImageType(new Uint8Array([]))).toBeNull();
  });
});

describe("scaledDimensions", () => {
  it("refuses an unknown or non-positive size instead of drawing 1x1", () => {
    expect(() => scaledDimensions(undefined, 600)).toThrow(
      /could not be opened/,
    );
    expect(() => scaledDimensions(0, 600)).toThrow(/could not be opened/);
    expect(() => scaledDimensions(800, Number.NaN)).toThrow(
      /could not be opened/,
    );
  });

  it("caps the long edge and keeps the aspect ratio", () => {
    expect(scaledDimensions(3200, 1600)).toEqual({ width: 1600, height: 800 });
    expect(scaledDimensions(1170, 2532)).toEqual({
      width: 739,
      height: MAX_LONG_EDGE,
    });
  });

  it("never upscales", () => {
    expect(scaledDimensions(800, 600)).toEqual({ width: 800, height: 600 });
  });
});

describe("dataUrlByteLength", () => {
  it("counts decoded bytes, honouring padding", () => {
    expect(dataUrlByteLength(dataUrlOf(10))).toBe(10);
    expect(dataUrlByteLength(dataUrlOf(11))).toBe(11);
    expect(dataUrlByteLength(dataUrlOf(12))).toBe(12);
    expect(dataUrlByteLength("")).toBe(0);
  });
});

describe("validateScreenshotFile", () => {
  it("accepts a PNG whose bytes say PNG", async () => {
    await expect(
      validateScreenshotFile(blob(PNG_MAGIC, "image/png")),
    ).resolves.toBe("image/png");
  });

  it("accepts a missing declared type when the bytes are a real image", async () => {
    await expect(validateScreenshotFile(blob(JPEG_MAGIC, ""))).resolves.toBe(
      "image/jpeg",
    );
  });

  it("refuses a declared type outside png/jpeg/webp", async () => {
    await expect(
      validateScreenshotFile(blob(GIF_MAGIC, "image/gif")),
    ).rejects.toMatchObject({
      code: "unsupported_type",
    });
    await expect(
      validateScreenshotFile(blob(PNG_MAGIC, "image/heic")),
    ).rejects.toMatchObject({
      code: "unsupported_type",
    });
  });

  it("refuses a renamed file whose bytes are not an accepted image", async () => {
    await expect(
      validateScreenshotFile(blob(GIF_MAGIC, "image/png")),
    ).rejects.toMatchObject({
      code: "unsupported_type",
    });
  });

  it("refuses empty and absurdly large inputs before decoding", async () => {
    await expect(
      validateScreenshotFile(new Blob([], { type: "image/png" })),
    ).rejects.toMatchObject({
      code: "empty",
    });
    const huge = {
      size: MAX_INPUT_BYTES + 1,
      type: "image/png",
      slice: () => blob(PNG_MAGIC, ""),
    };
    await expect(validateScreenshotFile(huge)).rejects.toMatchObject({
      code: "too_large_input",
    });
  });
});

describe("prepareScreenshot", () => {
  it("downscales the long edge to 1600 and keeps PNG when it fits", async () => {
    const { createCanvas, drawImage } = fakeCanvas({
      pngBytes: 500_000,
      jpegBytes: 100_000,
    });
    const decode = decodeTo(1170, 2532);
    const out = await prepareScreenshot(blob(PNG_MAGIC, "image/png"), {
      decode,
      createCanvas,
    });
    expect(createCanvas).toHaveBeenCalledWith(739, 1600);
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 739, 1600);
    expect(out).toMatchObject({
      mime: "image/png",
      width: 739,
      height: 1600,
      bytes: 500_000,
    });
    expect(out.dataUrl.startsWith("data:image/png;base64,")).toBe(true);
  });

  it("falls back to JPEG 0.85 when the PNG is over the cap", async () => {
    const { canvas, createCanvas } = fakeCanvas({
      pngBytes: MAX_UPLOAD_BYTES + 1,
      jpegBytes: 400_000,
    });
    const out = await prepareScreenshot(blob(PNG_MAGIC, "image/png"), {
      decode: decodeTo(1200, 900),
      createCanvas,
    });
    expect(canvas.toDataURL).toHaveBeenLastCalledWith("image/jpeg", 0.85);
    expect(out).toMatchObject({
      mime: "image/jpeg",
      bytes: 400_000,
      width: 1200,
      height: 900,
    });
  });

  it("refuses when even the JPEG is over the cap", async () => {
    const { createCanvas } = fakeCanvas({
      pngBytes: MAX_UPLOAD_BYTES + 10,
      jpegBytes: MAX_UPLOAD_BYTES + 1,
    });
    const err = await prepareScreenshot(blob(PNG_MAGIC, "image/png"), {
      decode: decodeTo(1600, 1600),
      createCanvas,
    }).catch((e) => e);
    expect(err).toBeInstanceOf(ScreenshotPrepError);
    expect(err.code).toBe("too_large");
  });

  it("never decodes an invalid file", async () => {
    const decode = vi.fn();
    await expect(
      prepareScreenshot(blob(GIF_MAGIC, "image/gif"), {
        decode,
        createCanvas: vi.fn(),
      }),
    ).rejects.toMatchObject({ code: "unsupported_type" });
    expect(decode).not.toHaveBeenCalled();
  });

  it("maps a decode failure to a named error", async () => {
    const decode = vi.fn(async () => {
      throw new Error("boom");
    });
    await expect(
      prepareScreenshot(blob(JPEG_MAGIC, "image/jpeg"), {
        decode,
        createCanvas: vi.fn(),
      }),
    ).rejects.toMatchObject({ code: "decode_failed" });
  });
});
