"""POST /api/trade/import-screenshot and GET .../status."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import server
from src.api import feature_flags, rate_limit
from src.trade.market_trade_normalize import IdentityContext
from src.trade.screenshot_import import ocr
from src.trade.screenshot_import.ocr import FakeEngine, OcrTimeout
from src.trade.screenshot_import.service import validate_extraction

from .conftest import page

URL = "/api/trade/import-screenshot"
STATUS_URL = "/api/trade/import-screenshot/status"
H = {"x-test-user": "jason"}

WORDS = page(
    ("You give", 60, 40),
    ("You get", 660, 40),
    ("Patrick Mahomes QB KC", 60, 100),
    ("9,999", 480, 100),
    ("Bijan Robinson", 660, 100),
    ("2027 1st", 660, 160),
)


def _png(size=(1200, 800), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buf, format=fmt)
    return buf.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture()
def client(monkeypatch, directory, board):
    def _session(request):
        user = (getattr(request, "headers", None) or {}).get("x-test-user")
        if not user:
            return None
        method = "guest_pass" if user == "guest" else "password"
        return {"username": user, "auth_method": method}

    monkeypatch.setattr(server, "_get_auth_session", _session)
    monkeypatch.setattr(server, "_is_authenticated", lambda request: _session(request) is not None)
    monkeypatch.setattr(server, "latest_contract_data", board)
    monkeypatch.setattr(
        server,
        "_screenshot_identity_context",
        lambda: IdentityContext.from_directory(directory, source="test"),
    )
    engine = FakeEngine(WORDS)
    monkeypatch.setattr(server, "_screenshot_ocr_engine_factory", lambda: engine)
    rate_limit.reset_for_tests()
    ocr.reset_counters_for_tests()
    feature_flags.reload()
    yield TestClient(server.app)
    rate_limit.reset_for_tests()
    feature_flags.reload()


def test_success_returns_the_validated_extraction(client):
    res = client.post(URL, json={"image": _b64(_png()), "index": 1}, headers=H)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    validate_extraction(body)
    assert body["imageIndex"] == 1
    assert [it["boardName"] for it in body["sides"][0]["items"]] == ["Patrick Mahomes"]
    assert [it["boardName"] for it in body["sides"][1]["items"]] == [
        "Bijan Robinson",
        "2027 Round 1",
    ]
    metrics = server.screenshot_import_metrics()
    assert metrics["ocr"]["ok"] == 1 and metrics["route"]["ok"] >= 1


def test_data_url_prefix_is_accepted(client):
    res = client.post(URL, json={"image": "data:image/png;base64," + _b64(_png())}, headers=H)
    assert res.status_code == 200, res.text
    assert res.json()["imageIndex"] == 0


def test_status_endpoint(client, monkeypatch):
    res = client.get(STATUS_URL, headers=H)
    assert res.status_code == 200
    assert res.json() == {
        "available": True,
        "reason": None,
        "engine": "tesseract",
        "version": "fake",
        "enabled": True,
    }
    monkeypatch.setattr(
        server,
        "_screenshot_ocr_engine_factory",
        lambda: FakeEngine(available=False, reason="tesseract_not_installed", version=None),
    )
    body = client.get(STATUS_URL, headers=H).json()
    assert body["available"] is False and body["reason"] == "tesseract_not_installed"


def test_status_with_the_real_engine_when_binary_missing(client, monkeypatch):
    from src.trade.screenshot_import.ocr import TesseractEngine

    ocr.clear_availability_cache()
    monkeypatch.setattr(ocr.shutil, "which", lambda _n: None)
    monkeypatch.setattr(server, "_screenshot_ocr_engine_factory", lambda: TesseractEngine())
    body = client.get(STATUS_URL, headers=H).json()
    assert body == {
        "available": False,
        "reason": "tesseract_not_installed",
        "engine": "tesseract",
        "version": None,
        "enabled": True,
    }
    ocr.clear_availability_cache()


def test_unauthenticated_is_401():
    c = TestClient(server.app)
    assert c.post(URL, json={"image": "x"}).status_code == 401
    assert c.get(STATUS_URL).status_code == 401


def test_guest_pass_is_read_only(client):
    res = client.post(URL, json={"image": _b64(_png())}, headers={"x-test-user": "guest"})
    assert res.status_code == 403
    assert res.json()["error"] == "guest_read_only"


def test_flag_off_is_404(client, monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_TRADE_SCREENSHOT_IMPORT", "0")
    feature_flags.reload()
    res = client.post(URL, json={"image": _b64(_png())}, headers=H)
    assert res.status_code == 404 and res.json()["error"] == "feature_disabled"
    assert client.get(STATUS_URL, headers=H).json()["enabled"] is False


def test_rate_limited_per_user(client, monkeypatch):
    monkeypatch.setattr(server, "_SCREENSHOT_RATE_CAPACITY", 2)
    body = {"image": _b64(_png())}
    assert client.post(URL, json=body, headers=H).status_code == 200
    assert client.post(URL, json=body, headers=H).status_code == 200
    res = client.post(URL, json=body, headers=H)
    assert res.status_code == 429
    assert res.json()["error"] == "rate_limited"
    assert int(res.headers["retry-after"]) >= 1
    # Another user has their own bucket.
    assert client.post(URL, json=body, headers={"x-test-user": "other"}).status_code == 200


@pytest.mark.parametrize(
    "payload,status,error",
    [
        ({"image": "!!!not-base64!!!"}, 400, "invalid_image_encoding"),
        ({"image": ""}, 400, "missing_image"),
        ({}, 400, "missing_image"),
        ({"image": "aGVsbG8=", "index": 4}, 400, "invalid_index"),
        ({"image": "aGVsbG8=", "index": True}, 400, "invalid_index"),
    ],
)
def test_bad_requests(client, payload, status, error):
    res = client.post(URL, json=payload, headers=H)
    assert res.status_code == status, res.text
    assert res.json()["error"] == error


def test_non_json_body(client):
    res = client.post(URL, content=b"not json", headers={**H, "content-type": "application/json"})
    assert res.status_code == 400 and res.json()["error"] == "invalid_json"


def test_unsupported_type_is_415(client):
    res = client.post(URL, json={"image": _b64(_png(fmt="GIF"))}, headers=H)
    assert res.status_code == 415 and res.json()["error"] == "unsupported_image_type"


def test_oversize_image_is_413(client):
    data = b"\x89PNG\r\n\x1a\n" + b"\0" * 3_050_000
    res = client.post(URL, json={"image": _b64(data)}, headers=H)
    assert res.status_code == 413 and res.json()["error"] == "image_too_large"


def test_body_over_the_route_cap_is_413_before_the_handler(client):
    res = client.post(URL, json={"image": "A" * 4_400_000}, headers=H)
    assert res.status_code == 413


def test_malformed_image_is_400(client):
    res = client.post(URL, json={"image": _b64(b"\x89PNG\r\n\x1a\n" + b"junk" * 40)}, headers=H)
    assert res.status_code == 400 and res.json()["error"] == "malformed_image"


def test_engine_unavailable_is_503(client, monkeypatch):
    monkeypatch.setattr(
        server,
        "_screenshot_ocr_engine_factory",
        lambda: FakeEngine(available=False, reason="tesseract_not_installed"),
    )
    res = client.post(URL, json={"image": _b64(_png())}, headers=H)
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "ocr_unavailable"
    assert body["message"] == (
        "Screenshot reading is not set up on this server yet (install the tesseract-ocr package)."
    )


def test_busy_is_503_with_retry_after(client):
    taken = 0
    try:
        while ocr._semaphore.acquire(blocking=False):
            taken += 1
        res = client.post(URL, json={"image": _b64(_png())}, headers=H)
    finally:
        for _ in range(taken):
            ocr._semaphore.release()
    assert res.status_code == 503 and res.json()["error"] == "ocr_busy"
    assert res.headers["retry-after"] == "5"


def test_timeout_is_504(client, monkeypatch):
    monkeypatch.setattr(
        server, "_screenshot_ocr_engine_factory", lambda: FakeEngine(raises=OcrTimeout("slow"))
    )
    res = client.post(URL, json={"image": _b64(_png())}, headers=H)
    assert res.status_code == 504 and res.json()["error"] == "ocr_timeout"


def test_no_board_loaded_is_explicit_per_item(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", None)
    body = client.post(URL, json={"image": _b64(_png())}, headers=H).json()
    reasons = {it["reason"] for s in body["sides"] for it in s["items"]}
    assert reasons == {"board_unavailable"}
