"""One preserved row of one source's board, in the source's OWN terms.

``ArchivedBoard.rows`` is a ``dict[str, float]`` — one number per name.  That
shape can hold a rank OR a value, never both, and it cannot hold a positional
rank, a tier, a position, a team, or the vendor's own id at all.  For the
sources this program acquires, those are not decoration:

* Dynasty Nerds publishes an IDP Top-275 whose entire content is **rank,
  positional rank and tier** — a float-per-name archive preserves none of it.
* Draft Sharks' cross-position signal is a **cardinal value**, and its vendor
  row id is what makes a join trustworthy.
* Dynasty Dealer publishes ``base_value`` and ``current_value`` **and** a
  vote count, and the difference between those numbers is the evidence.

So this is the per-row record, deliberately close to the existing
``src.data_models.contracts.RawAssetRecord`` vocabulary rather than a new one,
and narrowed to what preservation needs.

MISSING IS NEVER ZERO
─────────────────────

Every quantity here is optional and defaults to ``None``.  ``rank = 0`` and
``value = 0.0`` are *observations*, not "we did not see one", and the
constructor refuses the shapes that would blur them: a rank must be positive
if present (there is no rank zero), and a source declaring a value unit must
supply a value.  Nothing is coerced — a row that cannot be represented
honestly raises instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ArchivedRow", "ArchivedRowError"]


class ArchivedRowError(ValueError):
    """A row was constructed that cannot be true."""


@dataclass(frozen=True)
class ArchivedRow:
    """A source-native row.  Every derived quantity is optional."""

    #: The vendor's own name string, before any normalization.
    source_name: str
    #: The vendor's own row id, when it publishes one.  This is what makes a
    #: join defensible; a name-only join is recorded as such by its absence.
    source_player_id: str | None = None
    sleeper_id: str | None = None
    #: Canonical id, once identity resolution has run.  ``None`` means
    #: unresolved, and unresolved must stay unresolved.
    canonical_player_id: str | None = None
    #: The vendor's own position string (e.g. "EDGE"), never our family.
    source_position: str | None = None
    #: Our DL/LB/DB family, when it has been derived.  Kept BESIDE the native
    #: value rather than replacing it — "EDGE" is information DL discards.
    position_family: str | None = None
    team: str | None = None
    age: float | None = None
    overall_rank: int | None = None
    positional_rank: int | None = None
    tier: str | None = None
    #: The vendor's number, in the vendor's units.  Never our mapped value.
    value: float | None = None
    #: What ``value`` is denominated in, e.g. "3D Value +", "0-10000".
    value_unit: str | None = None
    #: Free-form, adapter-owned; e.g. base_value, votes, updated_at.
    native: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.source_name or "").strip():
            raise ArchivedRowError("a preserved row must carry the source's own name")
        for label, rank in (
            ("overall_rank", self.overall_rank),
            ("positional_rank", self.positional_rank),
        ):
            if rank is not None and rank < 1:
                raise ArchivedRowError(
                    f"{self.source_name}: {label}={rank} is not a rank. Ranks start at 1; "
                    "absent is None, and 0 must not stand in for it."
                )
        if self.value_unit and self.value is None:
            raise ArchivedRowError(
                f"{self.source_name}: value_unit={self.value_unit!r} was declared with no "
                "value. A unit without a number describes nothing."
            )

    @property
    def resolved(self) -> bool:
        return bool(self.canonical_player_id)

    def to_dict(self) -> dict[str, Any]:
        """Only what was observed.  Absent fields are omitted, never zeroed."""
        out: dict[str, Any] = {"sourceName": self.source_name}
        for key, val in (
            ("sourcePlayerId", self.source_player_id),
            ("sleeperId", self.sleeper_id),
            ("canonicalPlayerId", self.canonical_player_id),
            ("sourcePosition", self.source_position),
            ("positionFamily", self.position_family),
            ("team", self.team),
            ("age", self.age),
            ("overallRank", self.overall_rank),
            ("positionalRank", self.positional_rank),
            ("tier", self.tier),
            ("value", self.value),
            ("valueUnit", self.value_unit),
        ):
            if val is not None:
                out[key] = val
        if self.native:
            out["native"] = dict(self.native)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArchivedRow":
        return cls(
            source_name=str(data.get("sourceName") or ""),
            source_player_id=data.get("sourcePlayerId"),
            sleeper_id=data.get("sleeperId"),
            canonical_player_id=data.get("canonicalPlayerId"),
            source_position=data.get("sourcePosition"),
            position_family=data.get("positionFamily"),
            team=data.get("team"),
            age=data.get("age"),
            overall_rank=data.get("overallRank"),
            positional_rank=data.get("positionalRank"),
            tier=data.get("tier"),
            value=data.get("value"),
            value_unit=data.get("valueUnit"),
            native=dict(data.get("native") or {}),
        )
