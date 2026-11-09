"""
Sanity tests for the RankContext pipeline. Run with:
    python3 -m unittest discover -s tests -v
(also runs fine under pytest, if installed)

Each test builds a tiny throwaway git repo in a temp dir so tests are
self-contained and don't depend on any fixture living in the repo.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rankcontext.pipeline import run_pipeline  # noqa: E402


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _make_sample_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()

    (root / "README.md").write_text("# sample\nA tiny sample repo for tests.\n")
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "core.py").write_text("def central():\n    return 42\n")
    (root / "src" / "user.py").write_text(
        "from src.core import central\n\ndef use():\n    return central()\n"
    )
    (root / "src" / "orphan.py").write_text("x = 1\n" * 50)
    (root / "tests" / "test_core.py").write_text(
        "from src.core import central\n\ndef test_central():\n    assert central() == 42\n"
    )

    _run(["git", "init", "-q"], cwd=root)
    _run(["git", "config", "user.email", "t@t.com"], cwd=root)
    _run(["git", "config", "user.name", "T"], cwd=root)
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "-q", "-m", "init"], cwd=root)


class RankContextPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        _make_sample_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_runs_and_includes_all_within_generous_budget(self):
        result = run_pipeline(str(self.root), budget=100_000)
        self.assertEqual(result.total_candidate_files, 6)
        self.assertEqual(result.included_count, 6)
        self.assertEqual(result.excluded_count, 0)
        self.assertIn("### FILE: README.md", result.bundle_text)
        self.assertIn("### FILE: src/core.py", result.bundle_text)

    def test_central_file_ranks_above_orphan(self):
        result = run_pipeline(str(self.root), budget=100_000, manifest_only=True)
        lines = [l for l in result.manifest_text.splitlines() if l.strip()]
        order = [l.split()[0] for l in lines if l.split()[0] not in ("path", "#")]
        self.assertLess(order.index("src/core.py"), order.index("src/orphan.py"))

    def test_tight_budget_excludes_low_value_files(self):
        result = run_pipeline(str(self.root), budget=40)
        self.assertLessEqual(result.used_tokens, 40)
        self.assertGreaterEqual(result.excluded_count, 1)

    def test_manifest_only_produces_no_bundle(self):
        result = run_pipeline(str(self.root), budget=100_000, manifest_only=True)
        self.assertIsNone(result.bundle_text)
        self.assertIn("Manifest", result.manifest_text)

    def test_exclude_pattern_removes_matching_files(self):
        result = run_pipeline(str(self.root), budget=100_000, exclude_patterns=["tests/*"])
        self.assertEqual(result.total_candidate_files, 5)

    def test_weights_change_ranking_without_crashing(self):
        result = run_pipeline(str(self.root), budget=100_000, weights=(0.0, 1.0, 0.0))
        self.assertEqual(result.included_count, 6)

    def test_nonexistent_local_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            run_pipeline("/path/that/does/not/exist/at/all", budget=1000)

    def test_doc_boost_is_not_neutralized_by_normalization(self):
        # Regression test: a thin, barely-central README sitting at (or
        # near) the bottom of the raw-score distribution must still be
        # measurably lifted by its boost, not floored to 0 before the
        # boost is applied. See scoring.compute_scores for the fix.
        result = run_pipeline(str(self.root), budget=100_000, manifest_only=True)
        lines = [l for l in result.manifest_text.splitlines() if l.strip()]
        rows = {}
        for l in lines:
            parts = l.split()
            if parts and parts[0] not in ("path",):
                rows[parts[0]] = l
        readme_line = rows.get("README.md", "")
        self.assertNotIn(" 0.000 ", readme_line, "README boost was neutralized by normalization")


if __name__ == "__main__":
    unittest.main()
