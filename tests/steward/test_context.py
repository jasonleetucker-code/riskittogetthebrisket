from src.steward.context import ContextDocument, bundle


def test_context_bundle_is_order_independent_and_preserves_provenance():
    a = ContextDocument("a", "v1", "one")
    b = ContextDocument("b", "v2", "two")
    assert bundle([a, b]) == bundle([b, a])
    assert bundle([a, b])["documents"] == [
        {"identifier": "a", "version": "v1"},
        {"identifier": "b", "version": "v2"},
    ]
