"""OpenAPI is the only semantic owner of the generated frontend contract."""

import copy

import pytest

import server
from scripts import generate_leagues_contract


def test_committed_frontend_contract_matches_live_openapi():
    generate_leagues_contract.generate(check=True)
    hook = (generate_leagues_contract.ROOT / "frontend/components/useLeague.js").read_text(
        encoding="utf-8"
    )
    assert "parseLeaguesResponse(await res.json())" in hook


def test_schema_change_or_stale_output_fails_parity(tmp_path, monkeypatch):
    current = generate_leagues_contract._render(server.app.openapi())
    document = copy.deepcopy(server.app.openapi())
    document["components"]["schemas"]["PublicLeague"]["properties"]["newField"] = {"type": "string"}
    assert generate_leagues_contract._render(document) != current

    output = tmp_path / "leagues-contract.js"
    output.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(generate_leagues_contract, "OUTPUT", output)
    with pytest.raises(SystemExit, match="stale"):
        generate_leagues_contract.generate(check=True)
