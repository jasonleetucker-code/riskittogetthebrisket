"""Box-side TEST push per alert class (STAB-2) -- booleans only, never the URL."""

from __future__ import annotations

import json

from scripts import send_owner_test_alert as T

TOPIC = "https://ntfy.sh/private-topic-for-tests"


def _env(tmp_path, text):
    (tmp_path / ".env").write_text(text, encoding="utf-8")
    return tmp_path


def test_unconfigured_sends_nothing_and_exits_3(tmp_path):
    out, code = T.run(_env(tmp_path, "ALERT_ENABLED=false\n"), transport=lambda *a: 200)
    assert code == 3
    assert out["configured"] == {"ntfy": False}
    assert set(out["sent"]) == {k for k, _ in T.TEST_CLASSES}
    assert all(v is None for v in out["sent"].values())


def test_every_class_is_pushed_once_with_its_title(tmp_path):
    seen = []

    def transport(url, title, body, timeout):
        assert url == TOPIC
        seen.append(title)
        return 200

    out, code = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=transport)
    assert code == 0
    assert seen == [title for _, title in T.TEST_CLASSES]
    assert all(out["sent"].values())
    assert all(title.startswith("[TEST] ") for title in seen)


def test_a_failed_push_is_reported_and_exits_1(tmp_path):
    calls = {"n": 0}

    def transport(url, title, body, timeout):
        calls["n"] += 1
        return 500 if calls["n"] == 2 else 200

    out, code = T.run(_env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n"), transport=transport)
    assert code == 1
    assert list(out["sent"].values()).count(False) == 1


def test_missing_env_file_is_unreadable_not_configured(tmp_path):
    out, code = T.run(tmp_path / "nope", transport=lambda *a: 200)
    assert code == 3
    assert out["envFileReadable"] is False


def test_main_output_is_public_safe_and_never_names_the_topic(tmp_path, capsys, monkeypatch):
    app = _env(tmp_path, f"NOTIFY_WEBHOOK_URL={TOPIC}\n")
    monkeypatch.setattr(T.owner_notify, "_urllib_transport", lambda *a: 200)
    code = T.main(["--app-dir", str(app)])
    printed = capsys.readouterr().out
    assert code == 0
    assert "ntfy.sh" not in printed and "private-topic" not in printed
    assert json.loads(printed)["configured"] == {"ntfy": True}
