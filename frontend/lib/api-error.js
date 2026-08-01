function firstMessage(value, depth = 0) {
  if (depth > 5 || value == null) return null;

  if (typeof value === "string") {
    const text = value.trim();
    return text || null;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const message = firstMessage(item, depth + 1);
      if (message) return message;
    }
    return null;
  }

  if (typeof value === "object") {
    for (const key of ["message", "detail", "title", "error"]) {
      const message = firstMessage(value[key], depth + 1);
      if (message) return message;
    }
    for (const nested of Object.values(value)) {
      const message = firstMessage(nested, depth + 1);
      if (message) return message;
    }
  }

  return null;
}

export function apiErrorMessage(value, status = null) {
  return firstMessage(value) || (status ? `HTTP ${status}` : "Request failed");
}
