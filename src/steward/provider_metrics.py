"""Provider adapter helpers. Canonical receipts never depend on one vendor."""
from __future__ import annotations
from typing import Any

def anthropic_usage(response: dict[str, Any], *, model: str, effort: str | None, request_class: str) -> dict[str, Any]:
    """Normalize only fields actually supplied by Anthropic-compatible usage payloads."""
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    def integer(name: str) -> int | None:
        value = usage.get(name)
        return value if isinstance(value, int) and value >= 0 else None
    input_tokens = integer("input_tokens")
    cache_read = integer("cache_read_input_tokens")
    cache_write = integer("cache_creation_input_tokens")
    return {
        "provider": "anthropic",
        "model": model,
        "effort": effort,
        "request_class": request_class,
        "input_tokens": input_tokens,
        "output_tokens": integer("output_tokens"),
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "uncached_input_tokens": None if input_tokens is None or cache_read is None else max(0, input_tokens - cache_read),
        "cache_hit_ratio": None if not input_tokens or cache_read is None else cache_read / input_tokens,
    }

def unavailable_usage(*, provider: str, model: str, request_class: str) -> dict[str, Any]:
    """Honest parity for providers that do not expose a metric."""
    return {"provider": provider, "model": model, "request_class": request_class, "input_tokens": None, "output_tokens": None, "cache_read_tokens": None, "cache_write_tokens": None, "uncached_input_tokens": None, "cache_hit_ratio": None}
