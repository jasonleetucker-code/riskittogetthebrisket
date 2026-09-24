"""Deletion/mutation tests for the durable Lane 6 planning contract."""

from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path
from scripts import check_planning_integrity as planning


class UIParallelGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for relative in dict.fromkeys(
            (planning.UI_CONTRACT, planning.UI_LEDGER, *planning.UI_POINTER_DOCUMENTS)
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(
                    (
                        "# Minimal structural fixture",
                        planning.UI_POLICY,
                        planning.UI_BATCHING,
                        planning.UI_CONTRACT,
                        planning.UI_LEDGER,
                        "docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md",
                        "docs/WORK_CLAIMS.md",
                    )
                ),
                encoding="utf-8",
            )

    def failures(self, root: Path | None = None) -> planning.Failures:
        failures = planning.Failures()
        planning.check_ui_parallel_governance(failures, self.root if root is None else root)
        return failures

    def test_current_repository_and_minimal_tree_pass(self) -> None:
        self.assertEqual([], self.failures())
        self.assertEqual([], self.failures(planning.REPO))

    def test_deleting_each_required_document_fails(self) -> None:
        for path in list(self.root.rglob("*.md")):
            with self.subTest(document=str(path.relative_to(self.root))):
                text = path.read_text(encoding="utf-8")
                path.unlink()
                self.assertTrue(self.failures())
                self.assertIn(str(path.relative_to(self.root)), "\n".join(self.failures()))
                path.write_text(text, encoding="utf-8")

    def test_empty_or_unreadable_contract_and_ledger_fail(self) -> None:
        for relative in (planning.UI_CONTRACT, planning.UI_LEDGER):
            path = self.root / relative
            original = path.read_bytes()
            for content in (b" \n", b"\xff"):
                with self.subTest(document=relative, content=content):
                    path.write_bytes(content)
                    self.assertTrue(self.failures())
            path.write_bytes(original)

    def test_each_front_door_pointer_is_required(self) -> None:
        for relative in planning.UI_POINTER_DOCUMENTS:
            path = self.root / relative
            original = path.read_text(encoding="utf-8")
            for target in (planning.UI_CONTRACT, planning.UI_LEDGER):
                with self.subTest(document=relative, target=target):
                    path.write_text(original.replace(target, "removed-pointer"), encoding="utf-8")
                    self.assertTrue(self.failures())
            path.write_text(original, encoding="utf-8")

    def test_policy_cannot_disappear_or_become_a_quoted_example(self) -> None:
        for relative in (planning.UI_CONTRACT, *planning.UI_POLICY_DOCUMENTS):
            path = self.root / relative
            original = path.read_text(encoding="utf-8")
            for replacement in ("", "UI policy: DEFER_UI_UNTIL_END", "> " + planning.UI_POLICY):
                with self.subTest(document=relative, replacement=replacement):
                    path.write_text(
                        original.replace(planning.UI_POLICY, replacement), encoding="utf-8"
                    )
                    self.assertTrue(self.failures())
            path.write_text(original, encoding="utf-8")

    def test_explicit_ideas_batching_field_is_required(self) -> None:
        path = self.root / "docs/BRISKET_IDEAS.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(planning.UI_BATCHING, ""), encoding="utf-8"
        )
        self.assertTrue(self.failures())

    def test_contract_and_ledger_authority_links_are_required(self) -> None:
        for relative, target in (
            (planning.UI_CONTRACT, "docs/PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md"),
            (planning.UI_CONTRACT, planning.UI_LEDGER),
            (planning.UI_LEDGER, planning.UI_CONTRACT),
            (planning.UI_LEDGER, "docs/WORK_CLAIMS.md"),
        ):
            with self.subTest(document=relative, target=target):
                path = self.root / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(target, ""), encoding="utf-8")
                self.assertTrue(self.failures())
                path.write_text(original, encoding="utf-8")

    def test_main_actually_invokes_the_guard(self) -> None:
        tree = ast.parse(Path(planning.__file__).read_text(encoding="utf-8"))
        main = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        calls = {
            node.func.id
            for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("check_ui_parallel_governance", calls)
