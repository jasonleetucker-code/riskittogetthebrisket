"""Certified web adoption preserves bytes and existing domain consumers."""

import copy
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests.serving import test_serving_pipeline
from src.serving import attestation
from src.serving.artifacts import ArtifactStore, CorruptArtifact
from src.serving.builder import prepare_payload
from src.serving.runtime import PreparedBytes
from src.serving.serialization import ASSET, KEY, load_web_generation, publish_generation
from starlette.requests import Request

board = test_serving_pipeline.board


@pytest.fixture
def signing(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    private, public = tmp_path / "issuer.pem", tmp_path / "verifier.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("RISKIT_SERVING_ATTESTATION_PRIVATE_KEY", str(private))
    monkeypatch.setenv("RISKIT_SERVING_ATTESTATION_PUBLIC_KEY", str(public))
    # Simulate a separately started, configured signing process in this fixture.
    monkeypatch.setattr(attestation, "_PROCESS_RUNTIME", attestation._runtime_identity())
    return key


def test_certified_adoption_keeps_wire_and_domain_parity(board, signing, tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "store")
    publish_generation(board, store=store)
    monkeypatch.delenv("RISKIT_SERVING_ATTESTATION_PRIVATE_KEY")
    adopted = load_web_generation(store.read_current(ASSET, KEY))
    assert adopted.contract == json.loads(board.views["full"].raw)
    assert adopted.raw == board.raw
    for name, old in board.views.items():
        actual = adopted.views[name]
        assert (actual.raw, actual.gzip, actual.etag) == (old.raw, old.gzip, old.etag)
        if name in {"rankings", "trade", "catalog"}:
            assert isinstance(actual, PreparedBytes)
            assert not hasattr(actual, "payload")
            assert dict(actual.metadata) == json.loads(old.raw).get("meta", {})
        else:
            assert actual.payload == json.loads(old.raw)
    for key, row in adopted.indexes["players"].items():
        assert row in adopted.contract["playersArray"]
        assert row == board.indexes["players"][key]


def test_issuer_rejects_self_consistent_wrong_projection(board, signing, tmp_path):
    views = dict(board.views)
    payload = copy.deepcopy(views["rankings"].payload)
    payload["playersArray"][0]["rankDerivedValue"] = 9876
    views["rankings"] = prepare_payload(payload)
    with pytest.raises(CorruptArtifact):
        publish_generation(replace(board, views=views), store=ArtifactStore(tmp_path / "store"))


def test_configured_reader_refuses_unsigned_bundle(board, tmp_path, monkeypatch):
    monkeypatch.delenv("RISKIT_SERVING_ATTESTATION_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("RISKIT_SERVING_ATTESTATION_PRIVATE_KEY", raising=False)
    store = ArtifactStore(tmp_path / "store")
    publish_generation(board, store=store)
    key = Ed25519PrivateKey.generate()
    public = tmp_path / "public.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("RISKIT_SERVING_ATTESTATION_PUBLIC_KEY", str(public))
    with pytest.raises(CorruptArtifact):
        load_web_generation(store.read_current(ASSET, KEY))


def test_live_handlers_serve_byte_only_league_and_detail_metadata(board, monkeypatch):
    import server
    from src.serving.league_views import prepare_league_views

    cfg = SimpleNamespace(key="main", scoring_profile="same")
    original = prepare_league_views(board, cfg)
    bundle = replace(
        original,
        views={
            name: PreparedBytes(view.raw, view.gzip, view.etag, name, view.metadata)
            for name, view in original.views.items()
        },
    )
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda request: cfg)
    monkeypatch.setattr(
        server, "_league_serving_reader", SimpleNamespace(capture=lambda key: (board, bundle))
    )
    scope = {
        "type": "http",
        "query_string": b"",
        "headers": [],
        "method": "GET",
        "path": "/api/read-models/rankings",
    }
    for name, endpoint in (
        ("rankings", server.get_prepared_rankings),
        ("trade", server.get_prepared_trade),
        ("catalog", server.get_prepared_catalog),
    ):
        response = asyncio.run(endpoint(Request(scope)))
        assert response.status_code == 200
        assert response.body == original.views[name].raw
        assert response.headers["x-payload-view"] == name
        conditional = Request(
            {**scope, "headers": [(b"if-none-match", response.headers["etag"].encode())]}
        )
        assert asyncio.run(endpoint(conditional)).status_code == 304
    key = next(iter(board.indexes["players"]))
    request = Request({**scope, "query_string": f"generation={board.generation_id}".encode()})
    detail = asyncio.run(server.get_prepared_player(key, request))
    assert detail.status_code == 200
    assert json.loads(detail.body)["meta"] == dict(bundle.views["catalog"].metadata)
    assert asyncio.run(server.get_prepared_player(key, Request(scope))).status_code == 409
