"""AL-0 versioned feature dictionary (A4): undefined features and redefinitions fail."""

from __future__ import annotations

import copy
import json

import pytest

from src.model_registry import feature_dictionary as fd

DOC = json.loads(fd.DEFAULT_DICTIONARY_PATH.read_text(encoding="utf-8"))


def _doc():
    return copy.deepcopy(DOC)


def test_the_committed_dictionary_validates_and_holds_definitions_only():
    d = fd.load_dictionary()
    assert d.features
    for f in DOC["features"]:
        assert set(f) <= set(fd.REQUIRED_FIELDS), f"{f['name']} carries non-definition fields"
        assert "value" not in f and "values" not in f


def test_it_is_seeded_only_with_what_the_adapted_producers_consume():
    from src.model_registry.learning_adapters import (
        HILL_FAMILY,
        HILL_FEATURES,
        SQ_FAMILY,
        SQ_FEATURES,
    )

    declared = {(f["name"], f["version"]) for f in (*HILL_FEATURES, *SQ_FEATURES)}
    assert set(fd.load_dictionary().features) == declared
    consumers = {c for f in DOC["features"] for c in f["allowedConsumers"]}
    assert consumers == {HILL_FAMILY, SQ_FAMILY}


def test_editing_a_definition_in_place_fails():
    doc = _doc()
    doc["features"][0]["missingSemantics"] = "treat missing as 0"
    with pytest.raises(fd.FeatureRedefinitionError, match="NEW version"):
        fd.build_dictionary(doc)


def test_two_definitions_of_one_version_fail():
    doc = _doc()
    dup = copy.deepcopy(doc["features"][0])
    dup["unit"] = "something else"
    dup["definitionHash"] = fd.definition_hash(dup)
    doc["features"].append(dup)
    with pytest.raises(fd.FeatureRedefinitionError, match="defined twice"):
        fd.build_dictionary(doc)


def test_a_new_version_is_how_a_definition_changes():
    doc = _doc()
    v2 = copy.deepcopy(doc["features"][0])
    v2["version"] = 2
    v2["unit"] = "a refined unit"
    v2["definitionHash"] = fd.definition_hash(v2)
    doc["features"].append(v2)
    d = fd.build_dictionary(doc)
    name = v2["name"]
    assert d.get(name, 1).unit != d.get(name, 2).unit


def test_a_manifest_referencing_an_undefined_feature_fails():
    d = fd.load_dictionary()
    with pytest.raises(fd.UndefinedFeatureError):
        fd.validate_manifest(
            d, consumer="hill_scope_masters", features=[{"name": "ros_strength", "version": 1}]
        )
    with pytest.raises(fd.UndefinedFeatureError):
        fd.validate_manifest(
            d,
            consumer="hill_scope_masters",
            features=[{"name": "source_board_native_value", "version": 9}],
        )


def test_a_manifest_that_restates_a_definition_differently_fails():
    d = fd.load_dictionary()
    with pytest.raises(fd.FeatureRedefinitionError):
        fd.validate_manifest(
            d,
            consumer="hill_scope_masters",
            features=[
                {"name": "source_board_native_value", "version": 1, "missingSemantics": "zero"}
            ],
        )


def test_a_consumer_not_allowed_fails():
    d = fd.load_dictionary()
    with pytest.raises(fd.FeatureDictionaryError, match="not an allowed consumer"):
        fd.validate_manifest(
            d,
            consumer="source_quality_weights",
            features=[{"name": "source_board_native_value", "version": 1}],
        )


def test_the_manifest_hash_is_order_independent_and_definition_bound():
    d = fd.load_dictionary()
    a = [
        {"name": "source_board_native_value", "version": 1},
        {"name": "provider_family", "version": 1},
    ]
    assert fd.validate_manifest(
        d, consumer="hill_scope_masters", features=a
    ) == fd.validate_manifest(d, consumer="hill_scope_masters", features=list(reversed(a)))


@pytest.mark.parametrize(
    "owner",
    [
        "src.nowhere.module:fn",
        "src.model_registry.training_manifest:not_a_name",
        "scripts.x:y",
        "nocolon",
    ],
)
def test_a_definition_owner_must_resolve_statically(owner):
    doc = _doc()
    doc["features"][0]["definitionOwner"] = owner
    doc["features"][0]["definitionHash"] = fd.definition_hash(doc["features"][0])
    with pytest.raises(fd.FeatureDictionaryError):
        fd.build_dictionary(doc)


@pytest.mark.parametrize("field", ["knownAtRule", "missingSemantics", "allowedConsumers"])
def test_missing_semantics_and_known_at_are_mandatory(field):
    doc = _doc()
    del doc["features"][0][field]
    with pytest.raises(fd.FeatureDictionaryError):
        fd.build_dictionary(doc)
