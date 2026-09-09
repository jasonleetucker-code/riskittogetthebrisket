import pytest
from src.steward.store import StewardStore


def test_store_is_append_only_and_proposals_are_not_promotions(tmp_path):
    store = StewardStore(tmp_path / "steward.sqlite")
    store.append_receipt("r", {"cache": None}, "2026-09-09T00:00:00Z")
    store.propose("p", {"change": "routing"})
    assert store.proposals() == [
        {"proposal_id": "p", "change": "routing", "status": "PROPOSED_CHALLENGER"}
    ]
    with pytest.raises(Exception):
        store.connection.execute("UPDATE steward_proposals SET status = 'ACCEPTED'")
