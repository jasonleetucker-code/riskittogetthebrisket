from src.intel import platform_ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.sharp import market

NOW = 1_800_000_000_000


def _batch():
    return NormalizedBatch(
        platform="ffpc",
        managers=[NormalizedManager.build("ffpc", "league:L1:team:1")],
        leagues=[NormalizedLeague.build("ffpc", "L1", format_type="dynasty")],
        transactions=[
            NormalizedTransaction.build(
                "ffpc",
                "T1",
                league_key="ffpc:L1",
                season="2026",
                week=1,
                transaction_type="trade",
                status="complete",
                created_ms=NOW - 1000,
            )
        ],
        movements=[
            NormalizedMovement.build(
                "ffpc",
                "M1",
                transaction_key="ffpc:T1",
                league_key="ffpc:L1",
                canonical_asset_id="P1",
                source_asset_id="name:p1",
                source_name="Public Player",
                asset_type="player",
                action="add",
                manager_key="ffpc:league:L1:team:1",
                roster_id="1",
                counterparty_manager_key=None,
                timestamp_ms=NOW - 1000,
            )
        ],
    )


def _config(enabled=True):
    return {
        "enabled": enabled,
        "allowProvisionalPublicInCombinedSignals": True,
        "provisionalPublicWeight": 0.55,
        "seedLeagues": [
            {
                "sourceLeagueId": "L1",
                "enabled": True,
                "allowProvisionalContribution": True,
            }
        ],
    }


def test_public_ffpc_activity_is_usable_but_never_claims_sharp_v2(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch(), path=path)
    selected, coverage = market.cohort_members(
        qualification="provisional",
        ledger_path=path,
        ffpc_config=_config(),
    )
    assert len(selected) == 1
    assert selected[0].qualification_method == "provisional_public"
    assert selected[0].quality == 0.55
    assert coverage["provisionalContributionEnabled"] is True

    payload = market.market_payload(
        window="30d",
        qualification="provisional",
        now_ms=NOW,
        ledger_path=path,
        ffpc_config=_config(),
    )
    assert payload["status"] == "ok"
    assert payload["assets"][0]["windows"]["30d"]["buys"] == 1
    assert payload["cohort"]["qualificationMethods"] == ["provisional_public"]


def test_disabling_ffpc_removes_provisional_members(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch(), path=path)
    selected, coverage = market.cohort_members(
        qualification="provisional",
        ledger_path=path,
        ffpc_config=_config(enabled=False),
    )
    assert selected == []
    assert coverage["provisionalContributionEnabled"] is False
