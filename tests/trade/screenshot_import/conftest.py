"""Shared fixtures for the screenshot-import tests (synthetic word boxes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.trade.market_trade_normalize import IdentityContext
from src.trade.screenshot_import.ocr import Word

REPO = Path(__file__).resolve().parents[3]
DIRECTORY = REPO / "tests" / "fixtures" / "identity_directory_subset.json"
FIXTURES = REPO / "tests" / "fixtures" / "screenshot_import"


def phrase(text: str, x: int, y: int, *, h: int = 20, conf: float = 95.0) -> list[Word]:
    """Word boxes for ``text`` laid out left-to-right from ``(x, y)``."""
    out: list[Word] = []
    cursor = x
    for token in text.split():
        width = max(4, int(len(token) * 0.55 * h))
        out.append(Word(text=token, conf=conf, left=cursor, top=y, width=width, height=h))
        cursor += width + int(0.35 * h)
    return out


def page(*rows: tuple[str, int, int]) -> list[Word]:
    words: list[Word] = []
    for text, x, y in rows:
        words.extend(phrase(text, x, y))
    return words


@pytest.fixture(scope="session")
def directory() -> dict:
    return json.loads(DIRECTORY.read_text(encoding="utf-8"))["players"]


@pytest.fixture()
def identity_ctx(directory) -> IdentityContext:
    return IdentityContext.from_directory(directory, source="test_fixture")


@pytest.fixture()
def board() -> dict:
    return json.loads((FIXTURES / "board.json").read_text(encoding="utf-8"))
