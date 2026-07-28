"""``player_position`` must resolve each player at most once per snapshot.

Backlog defect #3, recorded as *"/league SSR exceeds even a 5 s proxy
timeout on a cold backend"* and carried as needing live measurement. It
was measured on 2026-07-28, and the recorded framing was wrong in the way
that mattered: the cost is not a cold-start cost.

Measured against the live 3-season snapshot, ``GET /api/public/league``:

    warm (cached snapshot)   6.449s / 6.643s / 6.484s
    cold (``?refresh=1``)    6.418s

The snapshot cache made no difference because the snapshot was never the
expensive part. ``build_public_contract`` runs on **every** request and
took 7.26s of that on its own; resolving the cached snapshot took
approximately zero. "Cold backend" pointed attention at exactly the wrong
place.

Profiling the build found ``PublicLeagueSnapshot.player_position`` called
**514,020 times** in a single contract build — ``awards.py`` walks every
starter of every matchup of every week of every season, repeatedly, for
VORP, unit points, rookie-of-the-year and the season races. Each call
re-ran ``resolve_idp_position`` (15.3s cumulative of a 19.3s total). The
distinct key space is the league's player universe, about 4,600 entries.

Memoizing on the snapshot took the build to ~2.3s and the endpoint to
2.24-2.53s, under the 5s timeout the defect named.

**Output equivalence was verified, not assumed.** A first attempt to
diff memoized against uncached output reported them different; that was
a flaw in the check, not in the memo. The contract embeds wall-clock
stamps (``generatedAt``, ``asOf``), so two runs of the *same*
implementation never match byte-for-byte either. With ISO timestamps
normalised, memoized-vs-memoized and memoized-vs-uncached both hash
identically.

This test pins **call count, not wall time.** A timing assertion on a
shared CI runner is a flake generator, and it would not say what actually
went wrong if the memo were removed.
"""

from __future__ import annotations

import pytest

from src.public_league.snapshot import PublicLeagueSnapshot


def _snapshot_with(players: dict) -> PublicLeagueSnapshot:
    return PublicLeagueSnapshot(
        root_league_id="TEST",
        generated_at="2026-07-28T00:00:00Z",
        nfl_players=players,
    )


@pytest.fixture
def counting_resolver(monkeypatch):
    """Count calls into the expensive resolver."""
    calls: list[tuple] = []
    import src.utils.name_clean as nc

    real = nc.resolve_idp_position

    def counted(fantasy_positions, position):
        calls.append((tuple(fantasy_positions or ()), position))
        return real(fantasy_positions, position)

    monkeypatch.setattr(nc, "resolve_idp_position", counted)
    return calls


def test_repeated_lookups_resolve_once(counting_resolver):
    snap = _snapshot_with(
        {
            "1": {"position": "LB", "fantasy_positions": ["LB"]},
            "2": {"position": "WR", "fantasy_positions": ["WR"]},
        }
    )
    for _ in range(500):
        snap.player_position("1")
        snap.player_position("2")

    assert len(counting_resolver) == 2, (
        f"{len(counting_resolver)} resolver calls for 2 distinct players over "
        "1000 lookups. The contract build makes ~514k of these; without the "
        "memo it spends multiple seconds per request re-deriving the same "
        "answers."
    )


def test_the_memo_returns_the_same_answer_the_uncached_path_would(counting_resolver):
    """Equivalence, per player, including the fall-through cases."""
    import src.utils.name_clean as nc

    players = {
        "idp": {"position": "SAF", "fantasy_positions": ["DB"]},
        "off": {"position": "WR", "fantasy_positions": ["WR"]},
        "raw": {"position": "K", "fantasy_positions": []},
        "empty": {"position": "", "fantasy_positions": []},
    }
    snap = _snapshot_with(players)
    for pid, p in players.items():
        idp = nc.resolve_idp_position(p.get("fantasy_positions"), p.get("position"))
        expected = idp if idp else str(p.get("position") or "").upper()
        first = snap.player_position(pid)
        second = snap.player_position(pid)
        assert first == expected == second, pid


def test_misses_are_cached_too():
    """An unknown id must not re-probe on every call.

    Half a million lookups against a player dump that is missing entries
    is exactly the shape that made this slow, and returning ``""`` early
    is easy to leave outside the memo.
    """
    snap = _snapshot_with({})
    probes = []

    class _Dict(dict):
        def get(self, k, default=None):
            probes.append(k)
            return super().get(k, default)

    snap.nfl_players = _Dict()
    for _ in range(50):
        assert snap.player_position("ghost") == ""
    assert len(probes) == 1, f"missing player re-probed {len(probes)} times"


def test_falsy_ids_short_circuit_without_touching_the_cache():
    snap = _snapshot_with({"1": {"position": "QB", "fantasy_positions": ["QB"]}})
    for bad in (None, ""):
        assert snap.player_position(bad) == ""
    assert "_position_memo" not in snap.__dict__


def test_the_memo_is_invisible_to_dataclass_machinery():
    """Why it lives on ``__dict__`` and not in a ``field()``.

    The snapshot is persisted. A declared field would be picked up by
    ``dataclasses.asdict`` and written into the stored artifact, and
    would participate in equality.
    """
    import dataclasses

    snap = _snapshot_with({"1": {"position": "QB", "fantasy_positions": ["QB"]}})
    snap.player_position("1")
    assert snap.__dict__.get("_position_memo"), "memo did not populate"

    names = {f.name for f in dataclasses.fields(snap)}
    assert "_position_memo" not in names
    assert "_position_memo" not in dataclasses.asdict(snap)


def test_two_snapshots_do_not_share_a_memo():
    """The cache is per instance, so a refreshed snapshot cannot serve
    the previous one's answers."""
    a = _snapshot_with({"1": {"position": "LB", "fantasy_positions": ["LB"]}})
    b = _snapshot_with({"1": {"position": "WR", "fantasy_positions": ["WR"]}})
    assert a.player_position("1") == "LB"
    assert b.player_position("1") == "WR"
