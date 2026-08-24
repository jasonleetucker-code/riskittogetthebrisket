"""V1-36 / C3-PKG-01 — suggestions.py consumes the canonical package
IDENTITY primitive (``src.packages.PackageAsset.key``).

Deliberately separate from ``tests/packages/test_single_owner.py``, which
guards package-generation MECHANICS (combinatorial enumeration + topology
bound) — a different concept.  ``suggestions.py``'s four ``_generate_*``
functions keep their own needs-driven heuristic search (untouched by this
unit); what changed is ONLY how a per-asset dedup/membership key is
computed, and that computation must route through the owner rather than a
local ``.lower()``/``.strip()`` variant.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.trade.suggestions import (
    PlayerAsset,
    _identity_key,
    _side_identity,
    _generate_sell_high,
    _generate_buy_low,
    _generate_consolidation,
    _generate_positional_upgrades,
    analyze_roster,
)
from src.packages import PackageAsset, adapt_assets, side_key

_SUGGESTIONS_PATH = Path(inspect.getfile(analyze_roster))

_GENERATOR_FUNCS = {
    "_generate_sell_high": _generate_sell_high,
    "_generate_buy_low": _generate_buy_low,
    "_generate_consolidation": _generate_consolidation,
    "_generate_positional_upgrades": _generate_positional_upgrades,
}

#: Functions whose per-asset identity computation the migration must own —
#: the four generators plus the two balancer/equalizer helpers and the
#: roster/pool join point they all ultimately share.
_IDENTITY_CONSUMING_FUNCS = (
    "_generate_sell_high",
    "_generate_buy_low",
    "_generate_consolidation",
    "_generate_positional_upgrades",
    "_roster_balancer_candidates",
    "_pool_balancer_candidates",
    "analyze_roster",
)


def _fn_node(name: str) -> ast.AST:
    tree = ast.parse(_SUGGESTIONS_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"could not locate function {name!r} in {_SUGGESTIONS_PATH}")


def _source_of(name: str) -> str:
    """Raw source of one function, comments included."""
    text = _SUGGESTIONS_PATH.read_text(encoding="utf-8")
    return ast.get_source_segment(text, _fn_node(name)) or ""


def _code_of(name: str) -> str:
    """CODE ONLY -- comments stripped.

    Load-bearing, and learned the hard way: these guards look for the exact
    retired spellings (``s.receive[0].name``, ``f"{p1.name}|{p2.name}"``,
    ``"|".join(...)``), and the migrated code carries comments that NAME
    those retired spellings to explain what replaced them. A raw-text scan
    therefore flags the very functions that were correctly migrated, which
    is a false RED that would push someone to delete the explanation rather
    than fix real code. ``ast.unparse`` round-trips the AST, so ``#``
    comments are gone and only executable code is matched."""
    return ast.unparse(_fn_node(name))


class TestIdentityKeyRoutesThroughTheOwner:
    """``_identity_key`` itself must call the owner, not reimplement its
    formula — otherwise "consumes PackageAsset/package_key" would be true
    only by coincidence of matching output, not by actual routing."""

    def test_identity_key_source_references_package_asset(self):
        src = inspect.getsource(_identity_key)
        assert "PackageAsset" in src, (
            "_identity_key must construct/consume src.packages.PackageAsset "
            "rather than reimplementing its normalization inline"
        )

    def test_identity_key_output_matches_the_owner_directly(self):
        """Calling the helper must be observably the same as calling the
        owner's own PackageAsset(...).key -- not merely similar-looking."""
        for name in ["Ja'Marr Chase", "  Drake London  ", "DE'VON ACHANE", "", None]:
            expected = PackageAsset(asset_id="", name=name or "", position="", value=None).key
            assert _identity_key(name) == expected


class TestNoLocalBespokeIdentityRepresentationRemains:
    """The local, hand-rolled ``.lower()``/``.strip()`` normalization this
    unit replaced must not survive anywhere in the four generators, the
    balancer helpers, or the roster/pool join point -- a partial migration
    (some sites converted, some not) is a worse defect than the original,
    because it introduces a SECOND, silently-diverging representation
    inside one file."""

    def test_no_bespoke_lower_strip_identity_pattern_in_generators_or_joins(self):
        offenders = []
        for name in _IDENTITY_CONSUMING_FUNCS:
            src = _code_of(name)
            # A bespoke identity key built directly off `.name` via
            # `.lower()`/`.strip()` rather than `_identity_key(...)`.  This
            # does NOT flag `_identity_key` itself (matched by function name
            # exclusion) or unrelated `.strip()` calls on raw display-name
            # extraction (a different concern, out of this unit's scope).
            if ".name.lower()" in src or 'name or "").strip().lower()' in src:
                offenders.append(name)
        assert not offenders, (
            f"bespoke .lower()/.strip() identity key survives in: {offenders} "
            f"-- route through _identity_key(...) instead"
        )

    def test_every_generator_and_join_point_calls_identity_key(self):
        """Positive check, not just an absence check: every one of these
        functions must actually CALL the owner-routed helper at least once
        (except analyze_roster's C3-CON-01 block, which is covered by the
        blocked_names/sendable_keys assertions below) -- proving real
        consumption, not merely the absence of the old pattern."""
        missing = [
            name for name in _IDENTITY_CONSUMING_FUNCS if "_identity_key(" not in _code_of(name)
        ]
        assert not missing, f"these functions never call _identity_key(...) at all: {missing}"


#: Every function that keys a candidate package SIDE, and must therefore
#: route through the owner's ``side_key`` via ``_side_identity`` rather than
#: a hand-rolled string.  These are a DIFFERENT concept from the per-asset
#: keys above: they identify a whole side of a proposed trade.
_SIDE_KEYING_FUNCS = (
    "_generate_buy_low",  # tightest-gap dedup, bucketed by receive side
    "_generate_consolidation",  # give-pair already-tried set
    "_apply_quality_filters",  # receive-target repetition cap
)


class TestSideKeysRouteThroughTheOwner:
    """The three hand-rolled SIDE keys this module carried before V1-36
    (``s.receive[0].name``, ``f"{p1.name}|{p2.name}"``, and
    ``"|".join(sorted(p.name ...))``) must all be gone, replaced by the one
    owner-routed helper."""

    def test_side_identity_delegates_to_the_owner(self):
        src = inspect.getsource(_side_identity)
        assert "side_key" in src and "adapt_assets" in src, (
            "_side_identity must call src.packages.side_key over "
            "adapt_assets(...), not reimplement a side key"
        )

    def test_side_identity_matches_the_owner_directly(self):
        a = PlayerAsset(
            name="Ja'Marr Chase", position="WR", display_value=9582, calibrated_value=9582
        )
        b = PlayerAsset(
            name="  PUKA NACUA  ", position="WR", display_value=9079, calibrated_value=9079
        )
        assert _side_identity([a, b]) == side_key(adapt_assets([a, b]))

    def test_side_identity_is_order_independent(self):
        """The retired consolidation key ``f"{p1.name}|{p2.name}"`` was
        order-DEPENDENT, so one unordered pair could key two ways. The
        owner's side key sorts."""
        a = PlayerAsset(name="Alpha", position="RB", display_value=100, calibrated_value=100)
        b = PlayerAsset(name="Beta", position="WR", display_value=200, calibrated_value=200)
        assert _side_identity([a, b]) == _side_identity([b, a])

    def test_no_hand_rolled_side_key_survives(self):
        offenders = []
        for name in _SIDE_KEYING_FUNCS:
            src = _code_of(name)
            if "receive[0].name" in src or '"|".join(' in src or 'f"{p1.name}|{p2.name}"' in src:
                offenders.append(name)
        assert not offenders, (
            f"hand-rolled side key survives in: {offenders} -- route through "
            f"_side_identity(...) / src.packages.side_key instead"
        )

    def test_every_side_keying_function_calls_the_owner_routed_helper(self):
        missing = [n for n in _SIDE_KEYING_FUNCS if "_side_identity(" not in _code_of(n)]
        assert not missing, f"these functions never call _side_identity(...): {missing}"


def _engineered_pool_and_roster():
    def mk(name, pos, val):
        return PlayerAsset(
            name=name, position=pos, display_value=val, calibrated_value=val, source_count=6
        )

    pool = [
        mk("QB Starter A", "QB", 8000),
        mk("QB Starter B", "QB", 7500),
        mk("QB Depth C", "QB", 3000),
        mk("QB Depth D", "QB", 2900),
        mk("RB Starter A", "RB", 6000),
        mk("RB Starter B", "RB", 5800),
        mk("RB Starter C", "RB", 5700),
        mk("RB Depth D", "RB", 800),
        mk("RB Target", "RB", 6200),
        mk("WR Rostered", "WR", 3000),
        mk("WR Target Sell", "WR", 3200),
        mk("WR Target Buy", "WR", 3500),
        mk("TE Target Consol", "TE", 5000),
    ]
    roster_names = [
        "QB Starter A",
        "QB Starter B",
        "QB Depth C",
        "QB Depth D",
        "RB Starter A",
        "RB Starter B",
        "RB Starter C",
        "RB Depth D",
        "WR Rostered",
    ]
    return pool, roster_names


class TestGeneratorsStillExcludeRosteredAssets:
    """Behavioral proof (not just a source scan): with the identity
    computation migrated, a rostered asset must still never appear as a
    RECEIVE target -- the exact invariant a format mismatch between the
    join side and the lookup side would silently break."""

    def test_no_generator_ever_recommends_receiving_a_rostered_asset(self):
        pool, roster_names = _engineered_pool_and_roster()
        roster = analyze_roster(roster_names, pool)
        roster_set = {_identity_key(n) for n in roster_names}
        rostered_keys = {_identity_key(n) for n in roster_names}

        all_suggestions = []
        for fn in _GENERATOR_FUNCS.values():
            all_suggestions.extend(fn(roster, pool, roster_set))

        assert all_suggestions, "fixture must produce at least one suggestion to be a real test"
        for s in all_suggestions:
            for target in s.receive:
                assert _identity_key(target.name) not in rostered_keys, (
                    f"{target.name!r} is on the roster but was recommended as a receive "
                    f"target -- the identity join between roster_set and the generators "
                    f"has diverged"
                )

    def test_whitespace_and_case_noise_in_roster_names_does_not_leak_a_rostered_target(self):
        """The exact boundary this migration touches: roster names arriving
        with whitespace/case noise must still join correctly against the
        pool, so a noisy-but-identical name is still excluded as a target."""
        pool, roster_names = _engineered_pool_and_roster()
        noisy_roster_names = [f"  {n.upper()}  " for n in roster_names]
        roster = analyze_roster(noisy_roster_names, pool)
        assert roster.roster_size == len(roster_names), (
            "the noisy names must still all match the pool"
        )
        roster_set = {_identity_key(n) for n in noisy_roster_names}
        rostered_keys = {_identity_key(n) for n in roster_names}

        all_suggestions = []
        for fn in _GENERATOR_FUNCS.values():
            all_suggestions.extend(fn(roster, pool, roster_set))

        assert all_suggestions
        for s in all_suggestions:
            for target in s.receive:
                assert _identity_key(target.name) not in rostered_keys
