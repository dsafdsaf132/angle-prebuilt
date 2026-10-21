#!/usr/bin/env python3
"""Exercise the workflow's existing-release Bash branch without GitHub writes."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / "workflows/build.yml"


def run_existing_release(replace=False, draft=False, matching=True, manifest=True, asset_count=7):
    workflow = WORKFLOW.read_text(encoding="utf-8")
    branch = workflow.split('          if [[ -n "$release_json" ]]; then\n', 1)[1]
    # Stop at the outer new-release branch without depending on its comments.
    branch, boundary, _ = branch.partition('\n          else\n            ensure_release_tag\n')
    if not boundary:
        raise AssertionError("Could not locate the new-release branch boundary")
    assets = [f"asset-{index}" for index in range(7)]
    release = {"draft": draft, "assets": [{"name": name} for name in assets[:asset_count]]}
    values = {
        "release_json": json.dumps(release),
        "tag": "angle-dev-test",
        "tag_commit": "source-sha",
        "RELEASE_TARGET_SHA": "source-sha",
        "RELEASE_TITLE": "Dev test",
        "RELEASE_MANIFEST_PATH": "manifest.json" if manifest else "",
        "GITHUB_REPOSITORY": "test/angle",
        "REPLACE_PUBLISHED_DEV": str(replace).lower(),
    }
    script = "set -euo pipefail\n"
    script += "\n".join(f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n"
    script += "assets=(" + " ".join(f"release-assets/{name}" for name in assets) + ")\n"
    script += "ensure_release_tag() { :; }\n"
    script += "release_manifests_match() { " + ("true" if matching else "false") + "; }\n"
    script += 'gh() { printf "MOCK_GH %s\\n" "$*"; }\n'
    script += textwrap.dedent(branch)
    return subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                          env={"PATH": os.environ["PATH"]})


class ManualDevReleaseTests(unittest.TestCase):
    def test_manual_dev_overwrites_assets_and_updates_notes(self):
        result = run_existing_release(replace=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MOCK_GH release upload angle-dev-test", result.stdout)
        self.assertIn("--clobber", result.stdout)
        self.assertIn("--notes-file release-notes.md", result.stdout)
        self.assertNotIn("no changes made", result.stdout)

    def test_automatic_and_stable_published_releases_remain_unchanged(self):
        result = run_existing_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no changes made", result.stdout)
        self.assertNotIn("MOCK_GH", result.stdout)

    def test_manual_dev_can_restore_missing_assets(self):
        result = run_existing_release(replace=True, asset_count=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--clobber", result.stdout)

    def test_different_provenance_or_missing_manifest_never_uploads(self):
        for overrides in ({"matching": False}, {"manifest": False}):
            with self.subTest(overrides=overrides):
                result = run_existing_release(replace=True, **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("MOCK_GH", result.stdout)

    def test_existing_draft_upload_still_works(self):
        result = run_existing_release(draft=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--clobber", result.stdout)


if __name__ == "__main__":
    unittest.main()
