function canShareFiles(file) {
  try {
    return !!(navigator.share && navigator.canShare?.({ files: [file] }));
  } catch {
    return false;
  }
}

function isIOSDevice() {
  if (typeof navigator === "undefined") return false;
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/**
 * Capture one DOM region and send it through the app's established mobile
 * share/download behavior. A preview URL is returned for iOS because Safari's
 * download attribute does not save images to the camera roll.
 */
export async function captureElementImage(
  element,
  { filename, title, maxCanvasArea = 5_000_000 } = {},
) {
  if (!element) throw new Error("Screenshot target is unavailable");

  await document.fonts?.ready;
  const { default: html2canvas } = await import("html2canvas");
  const bounds = element.getBoundingClientRect();
  const rawWidth = Math.max(element.scrollWidth, Math.ceil(bounds.width), 1);
  const rawHeight = Math.max(element.scrollHeight, Math.ceil(bounds.height), 1);
  const dprScale = Math.min(window.devicePixelRatio || 1, 2);
  const areaScale = Math.sqrt(maxCanvasArea / (rawWidth * rawHeight));
  const scale = Math.min(dprScale, areaScale);

  const canvas = await html2canvas(element, {
    useCORS: true,
    scale,
    logging: false,
    imageTimeout: 5000,
    backgroundColor: null,
  });
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (value) =>
        value
          ? resolve(value)
          : reject(new Error("canvas toBlob returned null")),
      "image/png",
    );
  });
  const safeFilename = filename || `chaseupside-${new Date().toISOString().slice(0, 10)}.png`;
  const file = new File([blob], safeFilename, { type: "image/png" });

  if (canShareFiles(file)) {
    try {
      await navigator.share({ files: [file], title: title || "Chase Upside" });
      return { kind: "shared" };
    } catch (error) {
      if (error?.name === "AbortError") return { kind: "cancelled" };
    }
  }

  const url = URL.createObjectURL(blob);
  if (isIOSDevice()) return { kind: "preview", url };

  const link = document.createElement("a");
  link.href = url;
  link.download = safeFilename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  return { kind: "downloaded" };
}
