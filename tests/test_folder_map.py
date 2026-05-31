"""Smoke tests for folder-map.

Stdlib ``unittest`` only — no test dependencies, matching the tool itself.
Run from the project root with:

    python3 -m unittest discover -s tests

The load-bearing test is ``test_pipeline_is_read_only``: it proves the scanned
folder is byte-for-byte identical before and after a full run. That guarantee
is the whole product, so it gets a test.
"""

import contextlib
import getpass
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# The package lives in dna/ (our Software 3.0 source dir; dna/ ≈ src/).
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "dna"))

from folder_map import cli  # noqa: E402
from folder_map import report  # noqa: E402


def _run_cli(argv):
    """Call cli.main, swallowing its narration; return the exit code."""
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        return cli.main(["folder-map"] + argv)


def _snapshot(root):
    """Map every file under root -> (size, sha256). Used to prove read-only."""
    snap = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root))
            data = p.read_bytes()
            snap[rel] = (len(data), hashlib.sha256(data).hexdigest())
    return snap


class FolderMapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = []

    def tearDown(self):
        for d in self._tmp:
            shutil.rmtree(d, ignore_errors=True)

    def _tmpdir(self):
        d = tempfile.mkdtemp(prefix="fm-test-")
        self._tmp.append(d)
        return d

    def _make_fixture(self):
        """A messy folder with two directories that each clear the
        MIN_CLUSTER_FILES gate, so clustering actually produces clusters."""
        root = Path(self._tmpdir()) / "messy"
        (root / "proj" / "src").mkdir(parents=True)
        (root / "notes").mkdir()
        for name in ("README.md", "package.json", ".gitignore"):
            (root / "proj" / name).write_text(name)
        (root / "proj" / "src" / "main.py").write_text("print('hi')\n")
        (root / "proj" / "src" / "util.py").write_text("x = 1\n")
        for i in range(4):
            (root / "notes" / f"note{i}.md").write_text(f"note {i}\n")
        return root

    def test_pipeline_is_read_only(self):
        """A full run must not change a single byte of the scanned folder."""
        fixture = self._make_fixture()
        before = _snapshot(fixture)

        out = self._tmpdir()
        rc = _run_cli([str(fixture), "--out", out])

        self.assertEqual(rc, 0, "pipeline should succeed on a normal folder")
        self.assertEqual(before, _snapshot(fixture),
                         "scanned folder was modified — read-only violated")
        # And nothing was written *inside* the scanned folder.
        self.assertNotIn("folder-map-out", os.listdir(fixture))

    def test_artifacts_written_to_out(self):
        fixture = self._make_fixture()
        out = self._tmpdir()
        _run_cli([str(fixture), "--out", out])
        for artifact in ("inventory.jsonl", "clusters.json",
                         "report.md", "report.html"):
            self.assertTrue((Path(out) / artifact).exists(),
                            f"missing artifact: {artifact}")

    def test_clusters_json_shape(self):
        fixture = self._make_fixture()
        out = self._tmpdir()
        _run_cli([str(fixture), "--out", out])
        data = json.loads((Path(out) / "clusters.json").read_text())
        self.assertIn("summary", data)
        summary = data["summary"]
        for key in ("total_files_inventoried", "cluster_count",
                    "confidence_distribution", "unsorted_loose_count"):
            self.assertIn(key, summary)
        self.assertGreaterEqual(summary["cluster_count"], 1,
                                "fixture has two clusterable directories")

    def test_missing_target_is_handled(self):
        out = self._tmpdir()
        rc = _run_cli([str(Path(self._tmpdir()) / "does-not-exist"),
                       "--out", out])
        self.assertEqual(rc, 2, "a missing folder should exit 2, not crash")

    def test_redact_scrubs_home_and_user(self):
        home = os.path.expanduser("~")
        user = getpass.getuser()
        text = f"file at {home}/secret owned by {user}"
        scrubbed = report.redact(text)
        self.assertNotIn(home, scrubbed)
        if user:
            self.assertNotIn(user, scrubbed)


if __name__ == "__main__":
    unittest.main()
