"""Provider adapter helpers. Canonical receipts never depend on one vendor."""

from __future__ import annotations
from typing import Any, Mapping


def _usage_field(usage: Any, name: str) -> Any:
    """Read one usage field from either a mapping or the SDK's own object.

    Real production usage (`client.messages.stream(...).get_final_message().usage`)
    is an attribute-bearing SDK object, never a dict -- only test fixtures
    construct the dict form. Supporting both here, once, means every call
    site can pass whichever shape it actually has instead of each one
    hand-rolling its own `getattr(..., 0) or 0` (which is exactly the
    missing-coerced-to-zero bug this module exists to prevent).
    """
    if isinstance(usage, Mapping):
        return usage.get(name)
    return getattr(usage, name, None)


def anthropic_usage(
    response: Any, *, model: str, effort: str | None, request_class: str
) -> dict[str, Any]:
    """Normalize only fields actually supplied by an Anthropic usage payload.

    ``response`` is a mapping with a ``"usage"`` key; that key's value may
    itself be a plain dict (test fixtures) or the SDK's ``Usage`` object
    (real production responses) -- both are handled identically.
    """
    usage = response.get("usage") if isinstance(response, Mapping) else None

    def integer(name: str) -> int | None:
        value = _usage_field(usage, name)
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
        "uncached_input_tokens": None
        if input_tokens is None or cache_read is None
        else max(0, input_tokens - cache_read),
        "cache_hit_ratio": None
        if not input_tokens or cache_read is None
        else cache_read / input_tokens,
    }


def unavailable_usage(*, provider: str, model: str, request_class: str) -> dict[str, Any]:
    """Honest parity for providers that do not expose a metric."""
    return {
        "provider": provider,
        "model": model,
        "request_class": request_class,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "uncached_input_tokens": None,
        "cache_hit_ratio": None,
    }
