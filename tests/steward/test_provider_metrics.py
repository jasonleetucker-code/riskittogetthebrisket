from dataclasses import dataclass

from src.steward.provider_metrics import anthropic_usage, unavailable_usage


def test_anthropic_cache_metrics_are_parsed_when_reported():
    metrics = anthropic_usage(
        {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_input_tokens": 60,
                "cache_creation_input_tokens": 5,
            }
        },
        model="claude",
        effort="high",
        request_class="review",
    )
    assert metrics["uncached_input_tokens"] == 40
    assert metrics["cache_hit_ratio"] == 0.6


def test_missing_or_malformed_usage_stays_unknown_not_zero():
    metrics = anthropic_usage(
        {"usage": {"input_tokens": "100"}}, model="claude", effort=None, request_class="coding"
    )
    assert metrics["input_tokens"] is None
    assert metrics["cache_hit_ratio"] is None
    assert (
        unavailable_usage(provider="other", model="m", request_class="x")["cache_read_tokens"]
        is None
    )


@dataclass
class _FakeAnthropicUsage:
    """Shape of the real SDK's Usage object -- attributes, not a mapping.

    Real production usage (`client.messages.stream(...).get_final_message().usage`)
    is this shape, never the dict form the two tests above construct. Both
    call sites that read live usage (`src/api/chat.py`,
    `src/public_league/matchup_narrative.py`) pass an object like this one,
    not a dict -- this test is what actually proves the fix, not the
    dict-fixture tests above.
    """

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None


def test_the_real_sdk_usage_object_is_parsed_identically_to_a_dict():
    metrics = anthropic_usage(
        {"usage": _FakeAnthropicUsage(100, 10, 60, 5)},
        model="claude",
        effort="high",
        request_class="review",
    )
    assert metrics["input_tokens"] == 100
    assert metrics["cache_read_tokens"] == 60
    assert metrics["uncached_input_tokens"] == 40
    assert metrics["cache_hit_ratio"] == 0.6


def test_a_real_sdk_usage_object_with_no_cache_fields_stays_null_not_zero():
    # This is the exact bug that shipped in production: `usage.cache_read_input_tokens or 0`
    # silently turned "this provider/request reported nothing here" into a
    # genuine zero, which reads identically to "confirmed zero cache reads."
    metrics = anthropic_usage(
        {"usage": _FakeAnthropicUsage(100, 10, None, None)},
        model="claude",
        effort="high",
        request_class="review",
    )
    assert metrics["cache_read_tokens"] is None
    assert metrics["cache_write_tokens"] is None
    assert metrics["uncached_input_tokens"] is None
    assert metrics["cache_hit_ratio"] is None
