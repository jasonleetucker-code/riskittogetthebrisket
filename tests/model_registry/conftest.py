"""Shared fixtures for the model-registry tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _learning_store_may_use_pytest_tmp(tmp_path_factory, monkeypatch):
    """Explicitly opt pytest's base temp directory in as a learning-store root.

    ``receipt_store`` has no implicit temp-dir allowance (production never sets
    ``EXTRA_ALLOWED_ROOTS``); tests that write a store under ``tmp_path`` need
    this opt-in. The in-repository rule still runs first, so this cannot admit a
    path inside the checkout even when the checkout itself lives under %TEMP%."""
    from src.model_registry import receipt_store

    monkeypatch.setattr(
        receipt_store, "EXTRA_ALLOWED_ROOTS", (tmp_path_factory.getbasetemp().resolve(),)
    )
