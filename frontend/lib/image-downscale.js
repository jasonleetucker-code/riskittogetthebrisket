/**
 * image-downscale — prepare a trade screenshot for upload.
 *
 * The screenshot importer sends ONE image per JSON request as base64; the
 * backend caps request bodies at 2 MB.  So before anything leaves the
 * browser the image is:
 *
 *   1. validated — declared type in {png, jpeg, webp} AND the first bytes
 *      carry that format's magic number (a renamed file is refused);
 *   2. decoded — ``createImageBitmap`` with ``imageOrientation:
 *      "from-image"`` so a phone photo's EXIF rotation is applied, falling
 *      back to an ``<img>`` element where createImageBitmap is missing;
 *   3. downscaled — long edge at most ``MAX_LONG_EDGE`` px (never upscaled);
 *   4. re-encoded on a canvas — PNG when that fits ``MAX_UPLOAD_BYTES``
 *      (text stays crisp for OCR), else JPEG at quality 0.85.  A canvas
 *      re-encode carries no EXIF, so location metadata never uploads.
 *
 * An image that is still too large after all of that is REFUSED with a
 * named error rather than sent and rejected by the server.
 *
 * The pure helpers are exported for unit tests; ``prepareScreenshot``
 * accepts injected ``decode`` / ``createCanvas`` so jsdom tests need no
 * real image codec.
 */

export const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const MAX_LONG_EDGE = 1600;
export const MAX_UPLOAD_BYTES = Math.round(1.3 * 1024 * 1024);
// Refuse absurd inputs before decoding them: a 40 MB photo decoded to a
// bitmap can exhaust a phone's memory.  Screenshots are far smaller.
export const MAX_INPUT_BYTES = 25 * 1024 * 1024;
export const JPEG_QUALITY = 0.85;

/** A refusal with a stable machine-readable ``code`` the UI maps to copy. */
export class ScreenshotPrepError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ScreenshotPrepError";
    this.code = code;
  }
}

/**
 * The image format named by a file's first bytes, or null.
 *   PNG  89 50 4E 47 0D 0A 1A 0A
 *   JPEG FF D8 FF
 *   WebP "RIFF" ???? "WEBP"
 */
export function sniffImageType(bytes) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || []);
  if (
    b.length >= 8 &&
    b[0] === 0x89 &&
    b[1] === 0x50 &&
    b[2] === 0x4e &&
    b[3] === 0x47 &&
    b[4] === 0x0d &&
    b[5] === 0x0a &&
    b[6] === 0x1a &&
    b[7] === 0x0a
  ) {
    return "image/png";
  }
  if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    b.length >= 12 &&
    b[0] === 0x52 &&
    b[1] === 0x49 &&
    b[2] === 0x46 &&
    b[3] === 0x46 &&
    b[8] === 0x57 &&
    b[9] === 0x45 &&
    b[10] === 0x42 &&
    b[11] === 0x50
  ) {
    return "image/webp";
  }
  return null;
}

/** Target size with the long edge capped at ``maxEdge``; never upscales. */
export function scaledDimensions(width, height, maxEdge = MAX_LONG_EDGE) {
  const w = Math.max(1, Math.round(Number(width) || 0));
  const h = Math.max(1, Math.round(Number(height) || 0));
  const long = Math.max(w, h);
  if (long <= maxEdge) return { width: w, height: h };
  const scale = maxEdge / long;
  return {
    width: Math.max(1, Math.round(w * scale)),
    height: Math.max(1, Math.round(h * scale)),
  };
}

/** Decoded byte length of a base64 data URL (what the server will receive). */
export function dataUrlByteLength(dataUrl) {
  const s = String(dataUrl || "");
  const comma = s.indexOf(",");
  const b64 = comma >= 0 ? s.slice(comma + 1) : s;
  if (!b64) return 0;
  const padding = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor((b64.length * 3) / 4) - padding);
}

async function readHeadBytes(blob, n = 16) {
  const head = typeof blob.slice === "function" ? blob.slice(0, n) : blob;
  if (typeof head.arrayBuffer === "function") {
    return new Uint8Array(await head.arrayBuffer());
  }
  // Older engines: FileReader.
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(head);
  });
}

/**
 * Validate type + magic number.  Resolves to the sniffed MIME type; rejects
 * with ``ScreenshotPrepError`` ("unsupported_type" | "too_large_input" |
 * "empty").
 */
export async function validateScreenshotFile(file) {
  if (!file || typeof file !== "object") {
    throw new ScreenshotPrepError("empty", "No image was provided.");
  }
  const size = Number(file.size);
  if (Number.isFinite(size) && size === 0) {
    throw new ScreenshotPrepError("empty", "That file is empty.");
  }
  if (Number.isFinite(size) && size > MAX_INPUT_BYTES) {
    throw new ScreenshotPrepError(
      "too_large_input",
      "That image is too large to read. Use a screenshot rather than a full-resolution photo.",
    );
  }
  const declared = String(file.type || "").toLowerCase();
  // An empty declared type is allowed (some share sheets omit it); the
  // magic number below is the real check.
  if (declared && !ACCEPTED_IMAGE_TYPES.includes(declared)) {
    throw new ScreenshotPrepError(
      "unsupported_type",
      "Use a PNG, JPEG or WebP screenshot.",
    );
  }
  const sniffed = sniffImageType(await readHeadBytes(file));
  if (!sniffed) {
    throw new ScreenshotPrepError(
      "unsupported_type",
      "That file is not a PNG, JPEG or WebP image.",
    );
  }
  return sniffed;
}

async function defaultDecode(file) {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      // Some engines reject the options bag; fall through to <img>.
    }
  }
  if (
    typeof Image === "undefined" ||
    typeof URL?.createObjectURL !== "function"
  ) {
    throw new ScreenshotPrepError(
      "decode_failed",
      "This browser cannot read images.",
    );
  }
  const url = URL.createObjectURL(file);
  try {
    // <img> applies EXIF orientation by default (image-orientation: from-image).
    const img = await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("decode failed"));
      el.src = url;
    });
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function defaultCreateCanvas(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function sourceSize(img) {
  return {
    width: img.naturalWidth || img.width || 0,
    height: img.naturalHeight || img.height || 0,
  };
}

/**
 * Validate, decode, downscale and re-encode one screenshot.
 *
 * @param {File|Blob} file
 * @param {{ decode?: Function, createCanvas?: Function }} [deps]
 * @returns {Promise<{dataUrl: string, width: number, height: number,
 *   bytes: number, mime: string}>}
 */
export async function prepareScreenshot(file, deps = {}) {
  await validateScreenshotFile(file);
  const decode = deps.decode || defaultDecode;
  const createCanvas = deps.createCanvas || defaultCreateCanvas;

  let img;
  try {
    img = await decode(file);
  } catch (err) {
    if (err instanceof ScreenshotPrepError) throw err;
    throw new ScreenshotPrepError(
      "decode_failed",
      "That image could not be opened.",
    );
  }
  const src = sourceSize(img);
  if (!src.width || !src.height) {
    throw new ScreenshotPrepError(
      "decode_failed",
      "That image could not be opened.",
    );
  }
  const { width, height } = scaledDimensions(src.width, src.height);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new ScreenshotPrepError(
      "decode_failed",
      "This browser cannot resize images.",
    );
  }
  ctx.drawImage(img, 0, 0, width, height);
  if (typeof img.close === "function") img.close();

  let mime = "image/png";
  let dataUrl = canvas.toDataURL(mime);
  let bytes = dataUrlByteLength(dataUrl);
  if (bytes > MAX_UPLOAD_BYTES) {
    mime = "image/jpeg";
    dataUrl = canvas.toDataURL(mime, JPEG_QUALITY);
    bytes = dataUrlByteLength(dataUrl);
  }
  if (bytes > MAX_UPLOAD_BYTES) {
    throw new ScreenshotPrepError(
      "too_large",
      "That screenshot is still too large after resizing. Crop it to the trade and try again.",
    );
  }
  return { dataUrl, width, height, bytes, mime };
}
