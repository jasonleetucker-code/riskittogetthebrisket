"""V1-36 / C3-PKG-01 — ``suggestions.py`` consumes the canonical package
IDENTITY owner (``src.packages``), proven against EXECUTABLE STRUCTURE.

Deliberately separate from ``tests/packages/test_single_owner.py``, which
guards package-generation MECHANICS (combinatorial enumeration + topology
bound) — a different concept.  ``suggestions.py``'s four ``_generate_*``
functions keep their own needs-driven heuristic search (untouched by this
unit); what this file pins is ONLY that the per-asset and per-side identity
keys are COMPUTED BY the owner rather than re-derived here.

Why this file was rewritten
---------------------------
The retired ownership legs asked ``"PackageAsset" in inspect.getsource(...)``
and ``"side_key" in ... and "adapt_assets" in ...``.  ``getsource`` returns
DOCSTRINGS AND COMMENTS, and this module's identity helpers carry long
docstrings naming every one of those symbols to explain the migration.  The
guard was satisfied by its own explanation.

Measured, not assumed.  The full bypass — canonical import removed, both
helpers locally recreated byte-equivalently, owner wording retained in the
docstrings, plus decoy owner calls at module scope and inside a helper — ran
**11 passed** against the retired guard.  Two distinct escapes:

* **prose** — a text scan cannot distinguish a call from a mention;
* **decoy** — "this module (or this function) calls the owner somewhere" is
  satisfied by any unrelated call while the returned key is still local.

The rule enforced here instead is a DATAFLOW one, and it is the only one
both escapes fail:

    the value an identity helper RETURNS must be data-dependent on a call to
    the canonical owner.

A docstring cannot participate in dataflow.  A discarded decoy call is not on
the returned value's dependency chain.  No owner reference is matched as
source text anywhere below, so quote style, formatting and comments are
structurally incapable of changing a verdict.

Coverage is not a hardcoded list that goes stale silently: any NEW
module-level function whose return derives from a name-lowercasing
normalisation is discovered and must be declared.
"""

from __future__ import annotations

import ast
import copy
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

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

#: The canonical identity owner.  A submodule of it
#: (``src.packages.construction``) is the same owner reached by a longer path
#: and counts.
_OWNER_MODULE = "src.packages"

#: The owner's identity primitives.  ``package_key`` is included because it IS
#: one, even though this module deliberately has no call site for it (see the
#: recorded note in ``suggestions.py``): a future consumer routing through it
#: must read as owner-derived, not as a local reimplementation.
_OWNER_PRIMITIVES = frozenset({"PackageAsset", "adapt_assets", "side_key", "package_key"})

#: The module-level identity helpers this file owns.  Every one must return an
#: owner-derived value, and the discovery leg fails if a new one appears
#: without being declared here.
_IDENTITY_HELPERS = ("_identity_key", "_side_identity")

#: Functions whose per-asset identity computation the migration must own — the
#: four generators plus the two balancer/equalizer helpers and the roster/pool
#: join point they all ultimately share.
_IDENTITY_CONSUMING_FUNCS = (
    "_generate_sell_high",
    "_generate_buy_low",
    "_generate_consolidation",
    "_generate_positional_upgrades",
    "_roster_balancer_candidates",
    "_pool_balancer_candidates",
    "analyze_roster",
)

#: Every function that keys a candidate package SIDE, and must therefore route
#: through the owner's ``side_key`` via ``_side_identity`` rather than a
#: hand-rolled string.  A DIFFERENT concept from the per-asset keys above:
#: these identify a whole side of a proposed trade.
_SIDE_KEYING_FUNCS = (
    "_generate_buy_low",  # tightest-gap dedup, bucketed by receive side
    "_generate_consolidation",  # give-pair already-tried set
    "_apply_quality_filters",  # receive-target repetition cap
)

_GENERATOR_FUNCS = {
    "_generate_sell_high": _generate_sell_high,
    "_generate_buy_low": _generate_buy_low,
    "_generate_consolidation": _generate_consolidation,
    "_generate_positional_upgrades": _generate_positional_upgrades,
}


# ---------------------------------------------------------------------------
# Structural analyzer.  Everything below reads the AST.  Nothing reads text.
# ---------------------------------------------------------------------------


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_owner_module(dotted: str | None) -> bool:
    if not dotted:
        return False
    return dotted == _OWNER_MODULE or dotted.startswith(_OWNER_MODULE + ".")


def _is_type_checking_guard(node: ast.AST) -> bool:
    """``if TYPE_CHECKING:`` — imports inside it never execute, so they are
    not an executable dependency however canonical they look."""
    if not isinstance(node, ast.If):
        return False
    return any(
        (isinstance(sub, ast.Name) and sub.id == "TYPE_CHECKING")
        or (isinstance(sub, ast.Attribute) and sub.attr == "TYPE_CHECKING")
        for sub in ast.walk(node.test)
    )


class OwnershipAnalysis:
    """What one module actually BINDS from the canonical owner, and which of
    its functions actually COMPUTE their return value through it."""

    def __init__(self, source: str) -> None:
        self.tree = ast.parse(source)
        self.functions: dict[str, ast.AST] = {
            n.name: n
            for n in self.tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        #: local name -> owner attribute it binds (an ``as`` alias is followed)
        self.primitives: dict[str, str] = {}
        #: names bound to the owner MODULE, reached later as ``pkg.side_key``
        self.module_aliases: set[str] = set()
        self._collect_imports()
        self._memo: dict[str, bool] = {}

    # -- imports ------------------------------------------------------------

    def _collect_imports(self) -> None:
        skip: set[int] = set()
        for node in ast.walk(self.tree):
            if _is_type_checking_guard(node):
                skip.update(id(sub) for sub in ast.walk(node))
        for node in ast.walk(self.tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.ImportFrom):
                if _is_owner_module(node.module):
                    for alias in node.names:
                        if alias.name == "*":
                            # A star import binds the primitives without
                            # naming them; treat every one as bound.
                            self.primitives.update({p: p for p in _OWNER_PRIMITIVES})
                        else:
                            self.primitives[alias.asname or alias.name] = alias.name
                elif node.module == "src":
                    for alias in node.names:
                        if alias.name == "packages":
                            self.module_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_owner_module(alias.name):
                        # ``import src.packages`` binds ``src``; ``as pkg`` pkg.
                        self.module_aliases.add(alias.asname or alias.name.split(".")[0])

    @property
    def has_owner_binding(self) -> bool:
        return bool(self.primitives or self.module_aliases)

    def owner_calls(self) -> set[str]:
        """Every owner primitive actually CALLED anywhere in executable code."""
        out: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                resolved = self.resolve_owner_call(node)
                if resolved is not None:
                    out.add(resolved)
        return out

    def resolve_owner_call(self, call: ast.Call) -> str | None:
        """The owner attribute this call invokes, or ``None``.

        Handles ``side_key(...)``, an ``as`` alias, ``pkg.side_key(...)`` and
        ``src.packages.side_key(...)``.
        """
        func = call.func
        if isinstance(func, ast.Name):
            return self.primitives.get(func.id)
        if isinstance(func, ast.Attribute) and func.attr in _OWNER_PRIMITIVES:
            base = func.value
            if isinstance(base, ast.Name) and base.id in self.module_aliases:
                return func.attr
            if _is_owner_module(_dotted_name(base)):
                return func.attr
        return None

    # -- dataflow -----------------------------------------------------------

    @staticmethod
    def _local_assignments(fn: ast.AST) -> dict[str, list[ast.expr]]:
        """name -> every expression assigned to it inside this function.

        Includes walrus and ``for``/comprehension targets, so a value reaching
        the return through a loop variable is still followed.
        """
        out: dict[str, list[ast.expr]] = {}

        def _record(target: ast.AST, value: ast.expr | None) -> None:
            if value is None:
                return
            if isinstance(target, ast.Name):
                out.setdefault(target.id, []).append(value)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    _record(elt, value)

        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    _record(target, node.value)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                _record(node.target, node.value)
            elif isinstance(node, ast.NamedExpr):
                _record(node.target, node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                _record(node.target, node.iter)
            elif isinstance(node, ast.comprehension):
                _record(node.target, node.iter)
        return out

    @staticmethod
    def _returns(fn: ast.AST) -> list[ast.Return]:
        """Return statements belonging to THIS function, not to a nested one."""
        nested: set[int] = set()
        for node in ast.walk(fn):
            if node is not fn and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                nested.update(id(sub) for sub in ast.walk(node))
        return [
            node for node in ast.walk(fn) if isinstance(node, ast.Return) and id(node) not in nested
        ]

    def _direct_owner_call_in(self, expr: ast.expr, stack: frozenset[str]) -> bool:
        """A call to the owner — or to a module-local function that is itself
        owner-derived, so a legitimate refactor into a private helper is not a
        false RED while a chain of local reimplementations never bottoms out at
        the owner."""
        for node in ast.walk(expr):
            if not isinstance(node, ast.Call):
                continue
            if self.resolve_owner_call(node) is not None:
                return True
            callee = node.func.id if isinstance(node.func, ast.Name) else None
            if callee and callee in self.functions and callee not in stack:
                if self.owner_derived(callee, stack | {callee}):
                    return True
        return False

    @staticmethod
    def _names_in(expr: ast.expr) -> set[str]:
        return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}

    def owner_derived(self, name: str, stack: frozenset[str] = frozenset()) -> bool:
        """EVERY returned value of this function is data-dependent on an owner
        call.

        ``all``, not ``any``: a helper routing through the owner on one branch
        and reimplementing on another is a partial migration, which is the
        worse defect — two silently diverging representations in one function.

        Fixed-point over local assignments rather than recursive expansion:
        the recursive form re-walked the same subtrees per referenced name and
        took two minutes on this module when nothing short-circuited.
        """
        if not stack and name in self._memo:
            return self._memo[name]
        fn = self.functions.get(name)
        if fn is None:
            raise AssertionError(f"no module-level function named {name!r}")

        assignments = self._local_assignments(fn)
        tainted: set[str] = set()
        changed = True
        while changed:
            changed = False
            for local, exprs in assignments.items():
                if local in tainted:
                    continue
                for expr in exprs:
                    if self._direct_owner_call_in(expr, stack) or (self._names_in(expr) & tainted):
                        tainted.add(local)
                        changed = True
                        break

        rets = [r for r in self._returns(fn) if r.value is not None]
        verdict = bool(rets) and all(
            self._direct_owner_call_in(r.value, stack) or (self._names_in(r.value) & tainted)
            for r in rets
        )
        if not stack:
            self._memo[name] = verdict
        return verdict

    # -- discovery ----------------------------------------------------------

    def returns_lowercased_name(self, fn: ast.AST) -> bool:
        """ "This looks like an identity helper": the returned value is
        data-dependent on a string lowercasing.

        Lowercasing is the discriminator, not ``.strip()`` — stripping is
        ordinary input cleanup and three unrelated functions in this module do
        it, so keying on it would be a false-positive generator.
        """
        assignments = self._local_assignments(fn)

        def _lowers(expr: ast.expr) -> bool:
            return any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"lower", "casefold"}
                for node in ast.walk(expr)
            )

        tainted: set[str] = set()
        changed = True
        while changed:
            changed = False
            for local, exprs in assignments.items():
                if local in tainted:
                    continue
                for expr in exprs:
                    if _lowers(expr) or (self._names_in(expr) & tainted):
                        tainted.add(local)
                        changed = True
                        break

        return any(
            _lowers(r.value) or (self._names_in(r.value) & tainted)
            for r in self._returns(fn)
            if r.value is not None
        )


_LIVE = OwnershipAnalysis(_SUGGESTIONS_PATH.read_text(encoding="utf-8"))


def _unparsed(snippet: str) -> str:
    """A source needle normalised through the AST.

    Load-bearing for quote-invariance: ``ast.unparse`` emits one canonical
    quote style, so a needle built this way matches a haystack built the same
    way whether the code was written with ``'``, ``"`` or triple quotes.  The
    retired legs matched raw text and could be evaded by reformatting alone.
    """
    return ast.unparse(ast.parse(snippet, mode="eval"))


def _fn_node(name: str) -> ast.AST:
    node = _LIVE.functions.get(name)
    if node is None:
        raise AssertionError(
            f"no module-level function named {name!r} in {_SUGGESTIONS_PATH} — "
            f"every function this file guards is module-level today"
        )
    return node


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """A copy of ``node`` with every docstring removed.

    ``ast.unparse`` drops ``#`` comments but KEEPS docstrings — they are real
    ``Expr(Constant(str))`` statements.  Measured: scanning the unparsed
    ``_side_identity`` for the retired ``s.receive[0].name`` spelling MATCHES,
    because its docstring names that spelling to explain what replaced it.  A
    docstring-inclusive scan therefore flags the correctly-migrated function
    and, worse, could be SATISFIED by prose — the exact defect this file
    exists to close.
    """
    clone = copy.deepcopy(node)
    for sub in ast.walk(clone):
        if isinstance(sub, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(sub, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                sub.body = body[1:] or [ast.Pass()]
    return clone


def _code_of(name: str) -> str:
    """EXECUTABLE CODE ONLY — comments AND docstrings stripped, quotes
    normalised.

    Load-bearing, and learned twice: these legs look for retired spellings, and
    the migrated code carries comments and docstrings that NAME those
    spellings to explain what replaced them.  A raw-text scan flags the very
    functions that were correctly migrated — and a scan that prose can satisfy
    is the defect, not a stylistic preference.
    """
    return ast.unparse(_strip_docstrings(_fn_node(name)))


def _called_names(name: str) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(_fn_node(name))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


# ---------------------------------------------------------------------------
# Synthetic fixtures: the mandated bypasses, in miniature.
# ---------------------------------------------------------------------------

#: The shipping shape.  Owner imported and CALLED into the returned value.
_HONEST = '''
from src.packages import PackageAsset, adapt_assets, side_key


def _identity_key(name):
    """Routed through src.packages.PackageAsset.key."""
    return PackageAsset(asset_id="", name=name or "", position="", value=None).key


def _side_identity(assets):
    """Routed through src.packages.side_key."""
    return side_key(adapt_assets(assets))
'''

#: Bypass 1 — duplicate local implementation, canonical import removed, owner
#: named only in prose.  Functionally identical output.
_PROSE_ONLY = '''
def _identity_key(name):
    """This routes through src.packages.PackageAsset.key, the C3-PKG-01
    owner, exactly as adapt_assets and side_key do."""
    # PackageAsset / adapt_assets / side_key — the canonical owner.
    return f"name:{(name or '').strip().lower()}"


def _side_identity(assets):
    """Identity of one side, from src.packages.side_key via adapt_assets."""
    return tuple(sorted(f"name:{(a.name or '').strip().lower()}" for a in assets))
'''

#: Bypass 2 — bypass 1 PLUS decoys: the owner is imported and genuinely
#: called, once at module scope and once inside the helper itself, while the
#: RETURNED key is still computed locally.
_DECOYED = '''
from src.packages import PackageAsset, adapt_assets, side_key


def _owner_touch():
    """A real, executable owner call with nothing to do with identity."""
    return PackageAsset(asset_id="", name="", position="", value=None).key


def _identity_key(name):
    """src.packages.PackageAsset.key — the C3-PKG-01 owner."""
    _decoy = PackageAsset(asset_id="", name="x", position="", value=None).key
    return f"name:{(name or '').strip().lower()}"


def _side_identity(assets):
    """src.packages.side_key via adapt_assets."""
    _decoy = adapt_assets(assets)
    keys = []
    for a in assets:
        keys.append(f"name:{(a.name or '').strip().lower()}")
    return tuple(sorted(keys))
'''

#: Half-migrated: owner on one branch, local reimplementation on another.
_PARTIAL = """
from src.packages import PackageAsset


def _identity_key(name):
    if name:
        return PackageAsset(asset_id="", name=name, position="", value=None).key
    return "name:"
"""

#: A legitimate refactor: the helper delegates to a private local function
#: which itself routes through the owner.  Must stay GREEN — a guard forbidding
#: this would push people to inline the call or delete the test.
_INDIRECT = """
from src.packages import PackageAsset


def _owner_key(name):
    return PackageAsset(asset_id="", name=name or "", position="", value=None).key


def _identity_key(name):
    return _owner_key(name)
"""

#: A chain of purely local helpers.  Superficially the same shape as
#: ``_INDIRECT`` and must stay RED — indirection is not ownership.
_INDIRECT_LOCAL = """
def _normalise(name):
    return (name or "").strip().lower()


def _owner_key(name):
    return f"name:{_normalise(name)}"


def _identity_key(name):
    return _owner_key(name)
"""

#: Typing-only import: binds nothing at runtime, so it is not a dependency.
_TYPE_CHECKING_ONLY = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.packages import PackageAsset


def _identity_key(name):
    return f"name:{(name or '').strip().lower()}"
"""

#: The owner reached by module alias rather than by name binding — a different
#: spelling of the same ownership, and it must be accepted.
_MODULE_ALIAS = """
import src.packages as pkg


def _identity_key(name):
    return pkg.PackageAsset(asset_id="", name=name, position="", value=None).key
"""


class TestTheAnalyzerRejectsEveryMandatedBypass:
    """Acceptance 3 and 5, proven on fixtures rather than asserted."""

    def test_the_honest_shape_is_accepted(self):
        """Non-vacuity: the guard must pass something, or it proves nothing."""
        a = OwnershipAnalysis(_HONEST)
        assert a.has_owner_binding
        for helper in _IDENTITY_HELPERS:
            assert a.owner_derived(helper)

    def test_prose_alone_cannot_satisfy_the_guard(self):
        a = OwnershipAnalysis(_PROSE_ONLY)
        assert not a.has_owner_binding, (
            "docstrings and comments naming the owner must not register as a "
            "dependency — this is the exact escape the retired guard had"
        )
        for helper in _IDENTITY_HELPERS:
            assert not a.owner_derived(helper)

    def test_a_decoy_owner_call_cannot_rescue_a_local_reimplementation(self):
        a = OwnershipAnalysis(_DECOYED)
        assert a.has_owner_binding, "fixture is only meaningful if the import really exists"
        assert a.owner_calls(), "the decoy calls must be real calls, not mentions"
        assert a.owner_derived("_owner_touch"), (
            "the decoy function itself IS owner-derived; the guard must still "
            "refuse the helpers that merely sit beside it"
        )
        for helper in _IDENTITY_HELPERS:
            assert not a.owner_derived(helper), (
                f"{helper} returns a locally-computed key; a discarded owner "
                f"call on an adjacent line is not on the returned value's "
                f"dependency chain"
            )

    def test_a_half_migrated_helper_is_refused(self):
        a = OwnershipAnalysis(_PARTIAL)
        assert not a.owner_derived("_identity_key"), (
            "one owner-derived branch and one local branch is two "
            "representations in one function, not a migration"
        )

    def test_delegating_to_a_local_helper_that_owns_correctly_is_accepted(self):
        a = OwnershipAnalysis(_INDIRECT)
        assert a.owner_derived(
            "_identity_key"
        ), "following module-local calls keeps a legitimate refactor green"

    def test_delegating_to_a_chain_of_local_helpers_is_still_refused(self):
        a = OwnershipAnalysis(_INDIRECT_LOCAL)
        for fn in ("_identity_key", "_owner_key", "_normalise"):
            assert not a.owner_derived(fn), (
                "a chain of local reimplementations never bottoms out at the "
                "owner, however many hops it takes"
            )

    def test_a_typing_only_import_is_not_an_executable_dependency(self):
        a = OwnershipAnalysis(_TYPE_CHECKING_ONLY)
        assert not a.has_owner_binding, "an if TYPE_CHECKING import never executes"
        assert not a.owner_derived("_identity_key")

    def test_the_owner_reached_by_module_alias_is_accepted(self):
        a = OwnershipAnalysis(_MODULE_ALIAS)
        assert a.has_owner_binding
        assert a.owner_derived("_identity_key"), (
            "pkg.PackageAsset(...) is the same ownership as a name binding; "
            "refusing it would make the guard a spelling preference"
        )


class TestQuoteStyleCannotAlterDetection:
    """Acceptance 4.  Structural by construction — the analyzer never reads
    source text — and pinned here so a text-matching leg cannot creep back in
    unnoticed."""

    @pytest.mark.parametrize("q", ['"', "'"], ids=["double", "single"])
    def test_the_verdict_is_identical_under_every_quote_style(self, q):
        src = (
            "from src.packages import PackageAsset\n\n\n"
            "def _identity_key(name):\n"
            f"    {q * 3}Routed through src.packages.PackageAsset.key.{q * 3}\n"
            f"    return PackageAsset(asset_id={q}{q}, name=name, "
            f"position={q}{q}, value=None).key\n"
        )
        a = OwnershipAnalysis(src)
        assert a.has_owner_binding
        assert a.owner_derived("_identity_key")

    def test_reformatting_a_local_reimplementation_does_not_make_it_green(self):
        single = "def _identity_key(name):\n    return 'name:' + (name or '').strip().lower()\n"
        double = 'def _identity_key(name):\n    return "name:" + (name or "").strip().lower()\n'
        verdicts = {
            OwnershipAnalysis(src).owner_derived("_identity_key") for src in (single, double)
        }
        assert verdicts == {False}, "quote style must not change the verdict"


class TestTheLiveModuleOwnsItsIdentity:
    """Acceptance 1, 2 and 6 against the shipping ``suggestions.py``."""

    def test_there_is_a_real_executable_dependency_on_the_owner(self):
        assert _LIVE.has_owner_binding, (
            f"{_SUGGESTIONS_PATH.name} must bind something from {_OWNER_MODULE} "
            f"in executable code — a docstring mention is not a dependency"
        )
        assert _LIVE.owner_calls(), (
            "no canonical owner primitive is CALLED anywhere in the module; a "
            "bound-but-uncalled import is a decoy, not a dependency"
        )

    @pytest.mark.parametrize("helper", _IDENTITY_HELPERS)
    def test_every_identity_helper_returns_an_owner_derived_value(self, helper):
        assert _LIVE.owner_derived(helper), (
            f"{helper} returns a value that does not depend on any "
            f"{_OWNER_MODULE} call — it computes identity locally"
        )

    def test_no_undeclared_module_level_identity_helper_exists(self):
        """Acceptance 6, kept honest over time: coverage is a hardcoded tuple,
        so something must fail when a SECOND identity helper appears."""
        discovered = sorted(
            name
            for name, fn in _LIVE.functions.items()
            if name not in _IDENTITY_HELPERS and _LIVE.returns_lowercased_name(fn)
        )
        assert not discovered, (
            f"these module-level functions return a lowercased-name key but are "
            f"not declared identity helpers: {discovered} — add them to "
            f"_IDENTITY_HELPERS (so they must be owner-derived) or stop "
            f"computing identity in them"
        )

    def test_the_guard_is_not_vacuous_against_this_module(self):
        """A function in this same module that is NOT identity-owning must be
        refused, or the assertions above could be passing for free."""
        non_owning = [
            name
            for name in _LIVE.functions
            if name not in _IDENTITY_HELPERS and not _LIVE.owner_derived(name)
        ]
        assert non_owning, (
            "every function in the module reports owner-derived, which would "
            "mean the analyzer answers True unconditionally"
        )


class TestRuntimeDelegationNotJustMatchingOutput:
    """Structure proves the call is written; this proves it is TAKEN.

    A local reimplementation can produce byte-identical output — the mandated
    bypass does exactly that — so an equality test against the owner cannot
    tell them apart.  Replacing the module's binding can: only a real
    delegation follows the replacement.
    """

    def test_identity_key_actually_calls_the_bound_owner(self, monkeypatch):
        import src.trade.suggestions as suggestions

        assert hasattr(suggestions, "PackageAsset"), (
            "suggestions.py no longer binds PackageAsset at module scope — the "
            "canonical dependency has been removed"
        )

        class _Sentinel:
            def __init__(self, **kwargs):
                self._name = kwargs.get("name", "")

            @property
            def key(self):
                return f"sentinel:{self._name}"

        monkeypatch.setattr(suggestions, "PackageAsset", _Sentinel)
        assert suggestions._identity_key("Ja'Marr Chase") == "sentinel:Ja'Marr Chase", (
            "_identity_key did not follow the module's PackageAsset binding — "
            "it is computing the key itself"
        )

    def test_side_identity_actually_calls_the_bound_owner(self, monkeypatch):
        import src.trade.suggestions as suggestions

        for attr in ("adapt_assets", "side_key"):
            assert hasattr(suggestions, attr), (
                f"suggestions.py no longer binds {attr} at module scope — the "
                f"canonical dependency has been removed"
            )

        monkeypatch.setattr(suggestions, "adapt_assets", lambda assets: list(assets))
        monkeypatch.setattr(suggestions, "side_key", lambda side: ("sentinel", len(side)))
        a = PlayerAsset(name="A", position="WR", display_value=1, calibrated_value=1)
        b = PlayerAsset(name="B", position="RB", display_value=2, calibrated_value=2)
        assert suggestions._side_identity([a, b]) == ("sentinel", 2), (
            "_side_identity did not follow the module's side_key/adapt_assets "
            "bindings — it is computing the side key itself"
        )


class TestIdentityMatchesTheOwnerExactly:
    """Output equality is still worth pinning — it catches an owner-routed call
    passing the WRONG arguments — but it is no longer the ownership proof,
    because a local copy satisfies it too."""

    def test_identity_key_output_matches_the_owner_directly(self):
        for name in ["Ja'Marr Chase", "  Drake London  ", "DE'VON ACHANE", "", None]:
            expected = PackageAsset(asset_id="", name=name or "", position="", value=None).key
            assert _identity_key(name) == expected

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
        order-DEPENDENT, so one unordered pair could key two ways.  The owner's
        side key sorts."""
        a = PlayerAsset(name="Alpha", position="RB", display_value=100, calibrated_value=100)
        b = PlayerAsset(name="Beta", position="WR", display_value=200, calibrated_value=200)
        assert _side_identity([a, b]) == _side_identity([b, a])


class TestNoLocalBespokeIdentityRepresentationRemains:
    """A partial migration — some sites converted, some not — is worse than the
    original defect, because it puts two silently-diverging representations
    inside one file.  These legs match AST-normalised source, so needle and
    haystack share one quote style and reformatting cannot evade them."""

    #: The retired per-asset spellings.
    _RETIRED_ASSET_KEYS = (
        ".name.lower()",
        _unparsed('(name or "").strip().lower()'),
    )
    #: The retired SIDE spellings.
    _RETIRED_SIDE_KEYS = (
        _unparsed("s.receive[0].name"),
        _unparsed('f"{p1.name}|{p2.name}"'),
    )

    def test_no_bespoke_per_asset_identity_pattern_survives(self):
        offenders = [
            name
            for name in _IDENTITY_CONSUMING_FUNCS
            if any(needle in _code_of(name) for needle in self._RETIRED_ASSET_KEYS)
        ]
        assert not offenders, (
            f"bespoke .lower()/.strip() identity key survives in: {offenders} "
            f"— route through _identity_key(...) instead"
        )

    def test_every_generator_and_join_point_calls_identity_key(self):
        """Positive check, not just an absence check: every one of these
        functions must actually CALL the owner-routed helper at least once,
        proving real consumption rather than the absence of the old pattern."""
        missing = [n for n in _IDENTITY_CONSUMING_FUNCS if "_identity_key" not in _called_names(n)]
        assert not missing, f"these functions never call _identity_key(...) at all: {missing}"

    def test_no_hand_rolled_side_key_survives(self):
        offenders = [
            name
            for name in _SIDE_KEYING_FUNCS
            if any(needle in _code_of(name) for needle in self._RETIRED_SIDE_KEYS)
        ]
        assert not offenders, (
            f"hand-rolled side key survives in: {offenders} — route through "
            f"_side_identity(...) / src.packages.side_key instead"
        )

    def test_every_side_keying_function_calls_the_owner_routed_helper(self):
        missing = [n for n in _SIDE_KEYING_FUNCS if "_side_identity" not in _called_names(n)]
        assert not missing, f"these functions never call _side_identity(...): {missing}"

    def test_no_module_level_function_anywhere_hand_rolls_a_side_key(self):
        """The two lists above are POSITIVE checks on the functions we know
        key a side.  This is the negative half, and it deliberately scans
        EVERY module-level function — a retired spelling reappearing in a
        function nobody thought to list is the case a name list cannot see."""
        offenders = sorted(
            name
            for name in _LIVE.functions
            if any(needle in _code_of(name) for needle in self._RETIRED_SIDE_KEYS)
        )
        assert not offenders, (
            f"a retired hand-rolled side key spelling appears in: {offenders} — "
            f"route through _side_identity(...) / src.packages.side_key instead"
        )


class TestTheDependencyIsObservableAtImportTime:
    """The audit's own probe, run the way it has to be run.

    The V1-36 audit demonstrated the bypass by showing ``src.packages`` absent
    from ``sys.modules`` after importing ``suggestions``.  Asserting that in
    THIS process would be vacuous — this test module imports the owner itself
    at the top — so it runs in a clean interpreter that imports nothing but
    the module under test.
    """

    def test_importing_suggestions_imports_the_canonical_owner(self):
        probe = "import sys; import src.trade.suggestions; " "print('src.packages' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(_SUGGESTIONS_PATH.parents[2]),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"the probe interpreter failed:\n{result.stderr[-2000:]}"
        assert result.stdout.strip() == "True", (
            "importing src.trade.suggestions did not import src.packages — the "
            "module has no runtime dependency on the canonical identity owner"
        )


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
    """Behavioural proof (not just a source scan): with the identity
    computation owned elsewhere, a rostered asset must still never appear as a
    RECEIVE target — the exact invariant a format mismatch between the join
    side and the lookup side would silently break."""

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
                    f"target — the identity join between roster_set and the generators "
                    f"has diverged"
                )

    def test_whitespace_and_case_noise_in_roster_names_does_not_leak_a_rostered_target(self):
        """The exact boundary this migration touches: roster names arriving
        with whitespace/case noise must still join correctly against the pool,
        so a noisy-but-identical name is still excluded as a target."""
        pool, roster_names = _engineered_pool_and_roster()
        noisy_roster_names = [f"  {n.upper()}  " for n in roster_names]
        roster = analyze_roster(noisy_roster_names, pool)
        assert roster.roster_size == len(
            roster_names
        ), "the noisy names must still all match the pool"
        roster_set = {_identity_key(n) for n in noisy_roster_names}
        rostered_keys = {_identity_key(n) for n in roster_names}

        all_suggestions = []
        for fn in _GENERATOR_FUNCS.values():
            all_suggestions.extend(fn(roster, pool, roster_set))

        assert all_suggestions
        for s in all_suggestions:
            for target in s.receive:
                assert _identity_key(target.name) not in rostered_keys
