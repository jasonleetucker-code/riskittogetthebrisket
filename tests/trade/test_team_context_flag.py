"""C3-CTX-01 — one reading of ``useTeamContext`` for every trade route."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.trade.team_context import team_context_requested


@pytest.mark.parametrize(
    "body,expected",
    [
        ({}, True),
        (None, True),
        ({"useTeamContext": None}, True),
        ({"useTeamContext": "false"}, True),  # never a silent ON -> OFF
        ({"useTeamContext": 0}, True),
        ({"useTeamContext": True}, True),
        ({"useTeamContext": False}, False),
    ],
)
def test_only_an_explicit_false_turns_it_off(body, expected):
    assert team_context_requested(body) is expected


def test_server_routes_do_not_parse_the_flag_themselves():
    src = (Path(__file__).resolve().parents[2] / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    raw_reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "useTeamContext"
    ]
    assert raw_reads == [], "parse useTeamContext through src.trade.team_context"
