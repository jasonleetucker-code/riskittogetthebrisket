from src.steward.provider_metrics import anthropic_usage, unavailable_usage

def test_anthropic_cache_metrics_are_parsed_when_reported():
    metrics = anthropic_usage({"usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 60, "cache_creation_input_tokens": 5}}, model="claude", effort="high", request_class="review")
    assert metrics["uncached_input_tokens"] == 40
    assert metrics["cache_hit_ratio"] == 0.6

def test_missing_or_malformed_usage_stays_unknown_not_zero():
    metrics = anthropic_usage({"usage": {"input_tokens": "100"}}, model="claude", effort=None, request_class="coding")
    assert metrics["input_tokens"] is None
    assert metrics["cache_hit_ratio"] is None
    assert unavailable_usage(provider="other", model="m", request_class="x")["cache_read_tokens"] is None
