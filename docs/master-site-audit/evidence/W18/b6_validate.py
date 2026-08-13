#!/usr/bin/env python3
"""B6 real-data validation — W18-F001 + W18-F002 on the live contract.

Boots the real app against the real ``config/leagues/registry.json`` and
the live board on disk, and reports what each league-scoped endpoint
actually answers.  No fixtures, no monkeypatched registry: the point is
to show the shipped configuration going through the shipped code.

Requires ``data/leagues/scoring_*.json`` — run
``scripts/fetch_league_scoring.py`` first.

    python docs/master-site-audit/evidence/W18/b6_validate.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

# Same placeholder the test suite uses; this harness never authenticates
# a real user, it stubs the gate below.
os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from src.api import league_registry  # noqa: E402
from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: E402


def scoring_agreement(leagues: dict) -> dict:
    """Do these leagues share scoring — and could the question be asked?

    ``scoring_fingerprint_for_league`` returns ``None`` for a league whose
    snapshot is stale, missing, or recorded against another NFL season.
    Those are the fail-closed states W18-F001 introduced, and folding them
    into a set makes two of them collapse: ``len({None, None}) == 1``
    published ``fingerprintsAgree: true`` for two leagues neither of which
    could be identified.  Measured on the real registry 2026-08-13T09:39Z,
    both live leagues ``stale``/``null`` beside a ``true``.

    So comparability is reported separately from agreement, and agreement
    is ``None`` — never ``False`` — when the question could not be asked.
    ``False`` would assert a proven DIFFERENCE, which is a different claim
    from "unverifiable" and equally untrue here.  Same missing-is-never-
    zero rule the product applies to ``dollarValue`` and
    ``budgetHeadroomAtP75``, applied to the evidence.
    """
    values = list(leagues.values())
    fingerprints = [v.get("scoringFingerprint") for v in values]
    comparable = bool(fingerprints) and all(bool(f) for f in fingerprints)
    return {
        "labelsAgree": len({v.get("scoringProfile") for v in values}) == 1,
        "fingerprintsComparable": comparable,
        "fingerprintsAgree": (len(set(fingerprints)) == 1) if comparable else None,
    }


def main() -> int:
    out: dict = {"leagues": {}, "endpoints": {}, "contract": {}}

    for cfg in league_registry.active_leagues():
        out["leagues"][cfg.key] = {
            "scoringProfile": cfg.scoring_profile,
            "scoringFingerprint": league_registry.scoring_fingerprint_for_league(cfg),
            "evidenceState": league_registry.scoring_evidence_state(cfg),
            "snapshot": str(league_registry.scoring_snapshot_path(cfg.sleeper_league_id)),
        }
    out["snapshotMaxAgeHours"] = league_registry.SCORING_SNAPSHOT_MAX_AGE_HOURS

    keys = list(out["leagues"])
    out.update(scoring_agreement(out["leagues"]))

    server._is_authenticated = lambda request: True  # noqa: SLF001

    async def _no_scrape(*_a, **_kw):
        return None

    server.run_scraper = _no_scrape

    with TestClient(server.app, raise_server_exceptions=True) as client:
        # Prime from the live board on disk — the same artifact production
        # serves — through the same function startup uses, so the meta
        # stamping under test actually runs.
        board = sorted(ROOT.glob("exports/latest/dynasty_data_*.json"))
        if board:
            server._prime_latest_payload(  # noqa: SLF001
                json.loads(board[-1].read_text(encoding="utf-8"))
            )
            out["contract"]["primedFrom"] = board[-1].name

        contract = server.latest_contract_data or {}
        meta = contract.get("meta") or {}
        sleeper = contract.get("sleeper") or {}
        out["contract"] = {
            "leagueKey": meta.get("leagueKey"),
            "scoringProfile": meta.get("scoringProfile"),
            "stampedFingerprint": meta.get("scoringFingerprint"),
            "derivedFromOwnSleeperBlock": scoring_fingerprint(sleeper.get("scoringSettings")),
            "resolvedByGate": server._contract_scoring_fingerprint(contract),  # noqa: SLF001
            "playersArray": len(contract.get("playersArray") or []),
        }

        for key in keys:
            per: dict = {}
            for path in (
                f"/api/data?leagueKey={key}",
                f"/api/terminal?leagueKey={key}",
                f"/api/draft-capital?leagueKey={key}",
            ):
                res = client.get(path)
                entry: dict = {"status": res.status_code}
                try:
                    body = res.json()
                except ValueError:
                    body = {}
                if res.status_code != 200:
                    entry["error"] = body.get("error")
                    entry["message"] = body.get("message")
                elif path.startswith("/api/data"):
                    block = body.get("sleeper") or {}
                    entry["sleeperDataReady"] = (body.get("meta") or {}).get("sleeperDataReady")
                    entry["sleeperLoadedLeagueKey"] = (body.get("meta") or {}).get(
                        "sleeperLoadedLeagueKey"
                    )
                    entry["sleeperIsNull"] = body.get("sleeper") is None
                    entry["leagueSpecificFieldsPresent"] = sorted(
                        f
                        for f in ("scoringSettings", "rosterPositions", "leagueSettings")
                        if block.get(f)
                    )
                per[path] = entry
            out["endpoints"][key] = per

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
