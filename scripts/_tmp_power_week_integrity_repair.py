from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Keep the W/L component on the exact same scored-week horizon as all-play
# and recent form. Sleeper roster settings can roll forward before matchup
# history is ingested, which is how Week 1 froze with 2-game records.
power = "src/ros/power_v2.py"
replace_once(
    power,
    "    0.10 official current-season record\n",
    "    0.10 as-of-week current-season record\n",
)
replace_once(
    power,
    '''    # Sleeper's roster settings are the authoritative current competitive\n    # record for the headline. Trend points cannot use today's roster settings\n    # retroactively, so they fall back to matchup-derived as-of records.\n    official_record_scores: dict[str, float] = {}\n    official_record_strings: dict[str, str] = {}\n    current_season = snapshot.current_season\n    if current_season is not None:\n        for roster in current_season.rosters or []:\n            rid = _metrics.roster_id_of(roster)\n            if rid is None:\n                continue\n            oid = _metrics.resolve_owner(registry, current_season.league_id, rid)\n            if not oid:\n                continue\n            rec = _metrics.regular_season_settings_record(roster)\n            games = int(rec["wins"]) + int(rec["losses"]) + int(rec["ties"])\n            if games:\n                official_record_scores[oid] = (\n                    float(rec["wins"]) + 0.5 * float(rec["ties"])\n                ) / games\n                official_record_strings[oid] = (\n                    f"{rec['wins']}-{rec['losses']}-{rec['ties']}"\n                    if rec["ties"]\n                    else f"{rec['wins']}-{rec['losses']}"\n                )\n''',
    '''    # Sleeper's roster settings are useful only when they describe the SAME\n    # scored-week horizon as the matchup-derived state below. Sleeper can roll\n    # roster settings forward before our weekly matchup ingest has caught up;\n    # accepting that newer record would mix Week N+1 W/L with Week N all-play,\n    # recent form, and evidence weights. That exact mixed-vintage state escaped\n    # into the 2026 Week 1 publication (scoredGames=1 with 2-game records).\n    #\n    # Per owner, trust Sleeper only when its game count matches the number of\n    # scored fantasy matchups represented by ``season_state``. Otherwise the\n    # matchup-derived record is the authoritative as-of-week answer.\n    official_record_scores: dict[str, float] = {}\n    official_record_strings: dict[str, str] = {}\n    official_record_games: dict[str, int] = {}\n    record_horizon_mismatches: list[tuple[str, int, int]] = []\n    current_season = snapshot.current_season\n    if current_season is not None:\n        for roster in current_season.rosters or []:\n            rid = _metrics.roster_id_of(roster)\n            if rid is None:\n                continue\n            oid = _metrics.resolve_owner(registry, current_season.league_id, rid)\n            if not oid:\n                continue\n            rec = _metrics.regular_season_settings_record(roster)\n            sleeper_games = int(rec["wins"]) + int(rec["losses"]) + int(rec["ties"])\n            scored_games = int(season_state.get(oid, _EMPTY_CAREER).get("games", 0))\n            if sleeper_games and sleeper_games == scored_games:\n                official_record_scores[oid] = (\n                    float(rec["wins"]) + 0.5 * float(rec["ties"])\n                ) / sleeper_games\n                official_record_strings[oid] = (\n                    f"{rec['wins']}-{rec['losses']}-{rec['ties']}"\n                    if rec["ties"]\n                    else f"{rec['wins']}-{rec['losses']}"\n                )\n                official_record_games[oid] = sleeper_games\n            elif sleeper_games != scored_games:\n                record_horizon_mismatches.append((oid, sleeper_games, scored_games))\n\n    if record_horizon_mismatches:\n        LOG.warning(\n            "[power_v2] ignoring %d Sleeper record(s) newer/older than the "\n            "matchup-derived Power horizon: %s",\n            len(record_horizon_mismatches),\n            record_horizon_mismatches,\n        )\n''',
)
replace_once(
    power,
    '''        if row["ownerId"] in official_record_strings:\n            row["record"] = official_record_strings[row["ownerId"]]\n            row["recordSource"] = "sleeper"\n        else:\n            current = season_state.get(row["ownerId"], _EMPTY_CAREER)\n            wins = round(float(current.get("wins", 0.0)))\n            games = int(current.get("games", 0))\n            row["record"] = f"{wins}-{games - wins}" if games else "0-0"\n            row["recordSource"] = "matchups"\n''',
    '''        if row["ownerId"] in official_record_strings:\n            row["record"] = official_record_strings[row["ownerId"]]\n            row["recordSource"] = "sleeper_as_of_week"\n            row["recordGames"] = official_record_games[row["ownerId"]]\n        else:\n            outcomes = list(season_outcomes.get(row["ownerId"], []))\n            wins = sum(1 for outcome in outcomes if outcome >= 0.75)\n            losses = sum(1 for outcome in outcomes if outcome <= 0.25)\n            ties = len(outcomes) - wins - losses\n            row["record"] = (\n                f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"\n            )\n            row["recordSource"] = "matchups_as_of_week"\n            row["recordGames"] = len(outcomes)\n''',
)


# 2) Make mixed-vintage publication impossible. Legacy synthetic tests that do
# not carry the new audit fields remain compatible, while every canonical
# power_v2 row now carries recordGames and recordSource and is checked.
snapshots = "src/ros/power_snapshots.py"
replace_once(
    snapshots,
    '''        "record": row.get("record"),\n        "pointsPerGame": components.get("pointsPerGame"),\n''',
    '''        "record": row.get("record"),\n        "recordGames": row.get("recordGames"),\n        "recordSource": row.get("recordSource"),\n        "pointsPerGame": components.get("pointsPerGame"),\n''',
)
replace_once(
    snapshots,
    '''\ndef record_snapshot(\n    *,\n    league_key: str,\n''',
    '''\ndef _validate_engine_publication_integrity(\n    section: dict[str, Any], rankings: list[dict[str, Any]]\n) -> None:\n    """Refuse an official week whose inputs describe different horizons.\n\n    The canonical engine publishes ``blend.scoredGames`` and, for every row,\n    ``recordGames``. Both must equal ``asOfWeek``. This makes the invariant a\n    write-boundary rule instead of relying on every upstream caller to remember\n    it. Older synthetic/legacy payloads that predate the audit fields are left\n    readable; current power_v2 output always supplies them.\n    """\n\n    week = section.get("asOfWeek")\n    if not isinstance(week, int) or isinstance(week, bool) or week < 0:\n        return\n\n    blend = section.get("blend") or {}\n    scored_games = blend.get("scoredGames")\n    if scored_games is not None:\n        try:\n            scored_games_int = int(scored_games)\n        except (TypeError, ValueError) as exc:\n            raise ValueError("Power publication scoredGames must be an integer") from exc\n        if scored_games_int != week:\n            raise ValueError(\n                f"Power publication horizon mismatch: asOfWeek={week} but "\n                f"blend.scoredGames={scored_games_int}"\n            )\n\n    for row in rankings:\n        record_games = row.get("recordGames")\n        record_source = row.get("recordSource")\n        if record_source in {"sleeper_as_of_week", "matchups_as_of_week"} and record_games is None:\n            raise ValueError(\n                f"Power publication row {row.get('ownerId')!r} has an as-of-week "\n                "record source but no recordGames audit field"\n            )\n        if record_games is None:\n            continue\n        try:\n            record_games_int = int(record_games)\n        except (TypeError, ValueError) as exc:\n            raise ValueError(\n                f"Power publication row {row.get('ownerId')!r} recordGames must be an integer"\n            ) from exc\n        if record_games_int != week:\n            raise ValueError(\n                f"Power publication record horizon mismatch for {row.get('ownerId')!r}: "\n                f"asOfWeek={week}, recordGames={record_games_int}"\n            )\n\n\ndef record_snapshot(\n    *,\n    league_key: str,\n''',
)
replace_once(
    snapshots,
    '''    path = snapshot_path(league_key, season, week)\n    if path.exists():\n        return path, False\n\n    movement = movement_against_previous(\n''',
    '''    path = snapshot_path(league_key, season, week)\n    if path.exists():\n        return path, False\n\n    _validate_engine_publication_integrity(section, rankings)\n\n    movement = movement_against_previous(\n''',
)
replace_once(
    snapshots,
    '''        "record": None,\n        "pointsPerGame": None,\n''',
    '''        "record": None,\n        "recordGames": None,\n        "recordSource": None,\n        "pointsPerGame": None,\n''',
)


# 3) Make LIVE vs OFFICIAL impossible to confuse on the page, and surface the
# known legacy Week 1 mixed-vintage artifact without rewriting history.
frontend = "frontend/app/league/sections/ros-power.jsx"
replace_once(
    frontend,
    '''function fmtRaw(v) {\n  if (v == null || !Number.isFinite(Number(v))) return "—";\n  return Number(v).toFixed(1);\n}\n\n''',
    '''function fmtRaw(v) {\n  if (v == null || !Number.isFinite(Number(v))) return "—";\n  return Number(v).toFixed(1);\n}\n\nfunction recordGameCount(record) {\n  if (typeof record !== "string") return null;\n  const parts = record.split("-").map((part) => Number(part));\n  if (parts.length < 2 || parts.some((part) => !Number.isFinite(part))) return null;\n  return parts.reduce((sum, part) => sum + part, 0);\n}\n\nfunction hasSnapshotIntegrityMismatch(snapshot) {\n  if (!snapshot || snapshot.week == null) return false;\n  const week = Number(snapshot.week);\n  if (!Number.isFinite(week) || week < 0) return false;\n  const scoredGames = Number(snapshot?.blend?.scoredGames);\n  if (Number.isFinite(scoredGames) && scoredGames !== week) return true;\n  return (snapshot.ranking || []).some((row) => {\n    const explicit = Number(row?.recordGames);\n    if (row?.recordGames != null && Number.isFinite(explicit)) return explicit !== week;\n    const parsed = recordGameCount(row?.record);\n    return parsed != null && parsed !== week;\n  });\n}\n\n''',
)
replace_once(
    frontend,
    '''  const isOfficial = !!official;\n\n  // Name the week the arrows are measured against, so "no movement" and\n''',
    '''  const isOfficial = !!official;\n  const integrityWarning = hasSnapshotIntegrityMismatch(official);\n\n  // Name the week the arrows are measured against, so "no movement" and\n''',
)
replace_once(
    frontend,
    '''          <div style={{ fontSize: "1rem", fontWeight: 900, letterSpacing: "0.02em" }}>League Power Rankings</div>\n          <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>\n            {season ? season : "Current season"}{week ? ` · Week ${week}` : ""}{isOfficial ? " · Official" : " · Current"}\n            {baselineLabel ? ` · ${baselineLabel}` : ""}\n          </div>\n''',
    '''          <div style={{ fontSize: "1rem", fontWeight: 900, letterSpacing: "0.02em" }}>\n            {isOfficial ? "Official League Power Rankings" : "League Power Rankings"}\n          </div>\n          <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>\n            {season ? season : "Current season"}{week ? ` · Week ${week}` : ""}{isOfficial ? " · Frozen weekly publication" : " · Current"}\n            {baselineLabel ? ` · ${baselineLabel}` : ""}\n          </div>\n''',
)
replace_once(
    frontend,
    '''      <div style={{ display: "grid", gap: 2 }}>\n''',
    '''      {integrityWarning ? (\n        <div\n          style={{\n            margin: "0 0 8px",\n            padding: "6px 8px",\n            border: "1px solid var(--amber)",\n            borderRadius: 6,\n            color: "var(--amber)",\n            fontSize: "0.64rem",\n          }}\n        >\n          Archive integrity warning: this older frozen card contains record data from a different week.\n          It is preserved for audit and never overrides the live ranking.\n        </div>\n      ) : null}\n\n      <div style={{ display: "grid", gap: 2 }}>\n''',
)
replace_once(
    frontend,
    '''  const resultsPct = Math.round(Number(blend.resultsWeight || 0) * 100);\n\n  // Render the formula from the weights actually applied. Missing canonical\n''',
    '''  const resultsPct = Math.round(Number(blend.resultsWeight || 0) * 100);\n  const latestOfficial = data?.shareSnapshot || data?.officialSnapshot || null;\n  const liveWeek = data?.asOfWeek ?? null;\n  const officialWeek = latestOfficial?.week ?? null;\n  const officialBehind =\n    liveWeek != null && officialWeek != null && Number(officialWeek) < Number(liveWeek);\n  const officialIntegrityWarning = hasSnapshotIntegrityMismatch(latestOfficial);\n\n  // Render the formula from the weights actually applied. Missing canonical\n''',
)
replace_once(
    frontend,
    '''      <Card title="Power Rankings">\n        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap", alignItems: "center" }}>\n''',
    '''      <Card title="Power Rankings">\n        <div\n          data-testid="power-ranking-status"\n          style={{\n            marginBottom: 10,\n            padding: "7px 9px",\n            border: "1px solid var(--border-bright, var(--border))",\n            borderRadius: 7,\n            fontSize: "0.68rem",\n            color: "var(--subtext)",\n          }}\n        >\n          <div style={{ fontWeight: 800, color: "var(--cyan)" }}>\n            LIVE RANKINGS{liveWeek != null ? ` · through Week ${liveWeek}` : ""}\n          </div>\n          {officialWeek != null ? (\n            <div>\n              Latest official share card: Week {officialWeek}. Official cards are frozen at publication.\n            </div>\n          ) : (\n            <div>No official weekly share card has been published yet.</div>\n          )}\n          {officialBehind ? (\n            <div style={{ color: "var(--amber)" }}>\n              The live table is newer than the latest official card, so their order can differ until the next publication.\n            </div>\n          ) : null}\n          {officialIntegrityWarning ? (\n            <div style={{ color: "var(--amber)" }}>\n              Archive integrity warning: the latest older card contains a record/week mismatch from the retired publication path.\n            </div>\n          ) : null}\n        </div>\n\n        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap", alignItems: "center" }}>\n''',
)
replace_once(
    frontend,
    '''            {shareOpen ? "Hide Share Card" : "Share Rankings"}\n''',
    '''            {shareOpen\n              ? "Hide Share Card"\n              : officialWeek != null\n                ? `Share Official Week ${officialWeek}`\n                : "Share Current Rankings"}\n''',
)
replace_once(
    frontend,
    '''              Sized to fit all 12 teams in one phone screenshot. Official weekly cards stay frozen after publication.\n''',
    '''              Sized to fit all 12 teams in one phone screenshot. Official weekly cards stay frozen after publication; the live table may move between publications.\n''',
)


# 4) Regression coverage: both the scoring path and the immutable publication
# boundary reject/avoid the exact Week-1-with-Week-2-record failure.
test_path = Path("tests/ros/test_power_week_integrity.py")
test_path.write_text(
    '''"""Power ranking as-of-week integrity regressions."""\n\nfrom __future__ import annotations\n\nimport pytest\n\nfrom src.ros import power_snapshots, power_v2\nfrom tests.ros.test_power_v2 import _make_snapshot\n\n\ndef test_live_power_ignores_sleeper_record_from_a_later_week(monkeypatch):\n    rosters = [\n        {\n            "owner_id": "a",\n            "roster_id": 1,\n            "settings": {"wins": 2, "losses": 0, "ties": 0},\n        },\n        {\n            "owner_id": "b",\n            "roster_id": 2,\n            "settings": {"wins": 1, "losses": 1, "ties": 0},\n        },\n    ]\n    snapshot = _make_snapshot(\n        rosters=rosters,\n        matchups_by_week={\n            1: [\n                {"roster_id": 1, "matchup_id": 1, "points": 120.0},\n                {"roster_id": 2, "matchup_id": 1, "points": 100.0},\n            ]\n        },\n    )\n    monkeypatch.setattr(power_v2, "_load_team_strength_rows", lambda snapshot=None: [])\n    monkeypatch.setattr(\n        power_v2,\n        "_load_team_strength_percentiles",\n        lambda snapshot=None: {"a": 0.75, "b": 0.25},\n    )\n\n    section = power_v2.build_section(snapshot)\n    rows = {row["ownerId"]: row for row in section["currentRanking"]}\n\n    assert section["asOfWeek"] == 1\n    assert section["blend"]["scoredGames"] == 1\n    assert rows["a"]["record"] == "1-0"\n    assert rows["b"]["record"] == "0-1"\n    assert rows["a"]["recordSource"] == "matchups_as_of_week"\n    assert rows["b"]["recordSource"] == "matchups_as_of_week"\n    assert rows["a"]["recordGames"] == 1\n    assert rows["b"]["recordGames"] == 1\n    assert rows["a"]["components"]["wl_record"] == 1.0\n    assert rows["b"]["components"]["wl_record"] == 0.0\n\n\ndef _publication_section(*, week: int, scored_games: int, record_games: int):\n    return {\n        "asOfSeason": "2026",\n        "asOfWeek": week,\n        "methodologyVersion": "test-v1",\n        "blend": {"scoredGames": scored_games},\n        "weights": {"team_ros_strength": 1.0},\n        "effectiveWeights": {"team_ros_strength": 1.0},\n        "currentRanking": [\n            {\n                "ownerId": "a",\n                "displayName": "A",\n                "teamName": "Team A",\n                "rank": 1,\n                "powerScore": 80.0,\n                "record": "2-0" if record_games == 2 else "1-0",\n                "recordGames": record_games,\n                "recordSource": "sleeper_as_of_week",\n                "rosStrengthPercentile": 0.5,\n                "components": {\n                    "team_ros_strength": 0.5,\n                    "all_play": 0.5,\n                    "recent": 0.5,\n                    "team_vorp": None,\n                    "wl_record": 1.0,\n                    "pointsPerGame": 100.0,\n                    "recentAvg": 100.0,\n                },\n            }\n        ],\n    }\n\n\ndef test_week_one_publication_refuses_two_game_record(tmp_path, monkeypatch):\n    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)\n    section = _publication_section(week=1, scored_games=1, record_games=2)\n\n    with pytest.raises(ValueError, match="record horizon mismatch"):\n        power_snapshots.record_snapshot(\n            league_key="main", section=section, scoring_fingerprint="abc"\n        )\n\n    assert not power_snapshots.snapshot_path("main", "2026", 1).exists()\n\n\ndef test_publication_refuses_blend_week_mismatch(tmp_path, monkeypatch):\n    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)\n    section = _publication_section(week=2, scored_games=1, record_games=2)\n\n    with pytest.raises(ValueError, match="horizon mismatch"):\n        power_snapshots.record_snapshot(\n            league_key="main", section=section, scoring_fingerprint="abc"\n        )\n\n\ndef test_aligned_week_publication_persists_audit_fields(tmp_path, monkeypatch):\n    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)\n    section = _publication_section(week=1, scored_games=1, record_games=1)\n\n    path, created = power_snapshots.record_snapshot(\n        league_key="main", section=section, scoring_fingerprint="abc"\n    )\n\n    assert created\n    payload = __import__("json").loads(path.read_text())\n    row = payload["ranking"][0]\n    assert row["recordGames"] == 1\n    assert row["recordSource"] == "sleeper_as_of_week"\n''',
    encoding="utf-8",
)

print("power week-integrity repair applied")
