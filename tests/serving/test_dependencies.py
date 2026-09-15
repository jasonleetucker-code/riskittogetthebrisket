"""Dependency changes invalidate only the affected accepted outputs."""

from dataclasses import replace
from types import MappingProxyType

import pytest

from src.serving import ArtifactStore, RejectedCandidate
from src.serving.dependencies import AssetSpec, DependencyError, DependencyRegistry


def spec(name, inputs=(), **changes):
    return AssetSpec(name, inputs, producer=f"build_{name}", version="v1", **changes)


def graph():
    return DependencyRegistry(
        [
            spec("injuries", priority=10, freshness_seconds=300, consumers=("Rankings", "Trade")),
            spec("market"),
            spec("scoring"),
            spec("canonical", ("market", "scoring")),
            spec("rankings", ("canonical", "injuries")),
            spec("trade", ("canonical", "injuries")),
            spec("catalog", ("canonical",)),
            spec("page", ("rankings", "trade")),
        ]
    )


def accepted(registry):
    generations = {name: f"{name}-output-1" for name in registry.order}
    fingerprints = {name: registry.fingerprint(name, generations) for name in registry.order}
    return generations, fingerprints


def test_diamond_graph_builds_each_consumer_once_in_dependency_order():
    registry = graph()
    assert registry.order[0] == "injuries"
    generations, fingerprints = accepted(registry)
    generations["injuries"] = "injuries-output-2"
    assert registry.plan(generations, fingerprints) == ("rankings", "trade", "page")
    assert registry.descendants(["injuries"]) == ("rankings", "trade", "page")
    assert len(registry.plan({}, {})) == len(registry.assets)
    for name in registry.order:
        assert all(
            registry.order.index(dependency) < registry.order.index(name)
            for dependency in registry.assets[name].inputs
        )


def test_unchanged_outputs_have_no_plan_even_when_observation_time_changes(tmp_path):
    registry = graph()
    generations, fingerprints = accepted(registry)
    store = ArtifactStore(tmp_path)
    metadata = {"modelVersion": "v1", "configHash": "none", "inputGenerations": {}}
    initial = store.publish("injuries", "global", {"data.json": b"[]"}, metadata)
    generations["injuries"] = initial.generation_id
    fingerprints = {name: registry.fingerprint(name, generations) for name in registry.order}
    refreshed = store.publish(
        "injuries", "global", {"data.json": b"[]"}, {**metadata, "sourceAsOf": "later-fetch"}
    )
    assert refreshed.generation_id == initial.generation_id
    generations["injuries"] = refreshed.generation_id
    assert registry.plan(generations, fingerprints) == ()


def test_model_and_scoring_changes_rebuild_their_descendants():
    registry = graph()
    generations, fingerprints = accepted(registry)
    revised = DependencyRegistry(
        replace(asset, version="v2") if asset.name == "canonical" else asset
        for asset in registry.assets.values()
    )
    affected = ("canonical", "catalog", "rankings", "trade", "page")
    assert revised.plan(generations, fingerprints) == affected
    generations["scoring"] = "new-actual-scoring-fingerprint"
    assert registry.plan(generations, fingerprints) == affected


def test_per_asset_config_changes_do_not_rebuild_unrelated_consumers():
    registry = graph()
    generations, fingerprints = accepted(registry)
    assert registry.plan(generations, fingerprints, {"rankings": "new-filter-config"}) == (
        "rankings",
        "page",
    )


def test_registration_input_order_and_observational_policy_do_not_change_compute_identity():
    registry = graph()
    generations, fingerprints = accepted(registry)
    reordered = DependencyRegistry(
        replace(
            asset,
            inputs=tuple(reversed(asset.inputs)),
            consumers=("Another consuming page",),
            freshness_seconds=123,
            priority=99,
        )
        for asset in reversed(list(registry.assets.values()))
    )
    assert reordered.plan(generations, fingerprints) == ()
    assert all(
        reordered.fingerprint(name, generations) == fingerprints[name] for name in registry.order
    )


@pytest.mark.parametrize(
    "specs, error",
    [
        ([spec("a"), spec("a")], "Duplicate asset"),
        ([spec("a", ("missing",))], "Missing dependencies"),
        ([spec("a", ("b",)), spec("b", ("a",))], "Dependency cycle"),
        ([spec("a", ("a",))], "Dependency cycle"),
    ],
)
def test_invalid_dependency_graphs_fail_before_any_work(specs, error):
    with pytest.raises(DependencyError, match=error):
        DependencyRegistry(specs)


def test_missing_input_generation_and_unknown_roots_are_explicit():
    registry = graph()
    with pytest.raises(DependencyError, match="Missing generation"):
        registry.fingerprint("canonical", {})
    with pytest.raises(DependencyError, match="Unknown asset"):
        registry.descendants(["typo"])
    with pytest.raises(DependencyError, match="Invalid output generation"):
        registry.plan({"injuries": {"sourceAsOf": "timestamp-is-not-a-generation"}}, {})


def test_iterable_inputs_are_captured_without_exhaustion():
    registry = DependencyRegistry([spec("source"), spec("rows", iter(["source"]))])
    assert registry.assets["rows"].inputs == ("source",)
    assert registry.descendants(["source"]) == ("rows",)


def test_failed_build_remains_pending_and_cannot_replace_accepted_output(tmp_path):
    registry = DependencyRegistry([spec("source"), spec("rankings", ("source",))])
    store = ArtifactStore(tmp_path)
    metadata = {"modelVersion": "v1", "configHash": "none", "inputGenerations": {"source": "old"}}
    old = store.publish("rankings", "global", {"rows.json": b"accepted"}, metadata)
    generations = {"source": "old", "rankings": old.generation_id}
    fingerprints = {name: registry.fingerprint(name, generations) for name in registry.order}
    generations["source"] = "new"
    pending_before = registry.plan(MappingProxyType(generations), MappingProxyType(fingerprints))
    assert pending_before == ("rankings",)
    with pytest.raises(RejectedCandidate):
        store.publish(
            "rankings",
            "global",
            {"rows.json": b"rejected"},
            {**metadata, "inputGenerations": {"source": "new"}},
            validator=lambda candidate: False,
        )
    assert store.read_current("rankings", "global").generation_id == old.generation_id
    assert registry.plan(generations, fingerprints) == pending_before
    new = store.publish(
        "rankings",
        "global",
        {"rows.json": b"accepted new output"},
        {**metadata, "inputGenerations": {"source": "new"}},
    )
    generations["rankings"] = new.generation_id
    fingerprints["rankings"] = registry.fingerprint("rankings", generations)
    assert registry.plan(generations, fingerprints) == ()
