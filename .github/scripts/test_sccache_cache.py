#!/usr/bin/env python3
import argparse
import contextlib
import io
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import angle_ci
import sccache_cache


def snapshot(cache_id, **extra):
    return {"id": cache_id, "key": f"{sccache_cache.CACHE_PREFIX}{cache_id}-1",
            "ref": sccache_cache.CACHE_REF,
            "created_at": f"2026-10-{cache_id:02d}T00:00:00Z", **extra}


class CompilerCacheTests(unittest.TestCase):
    def test_writer_policy(self):
        for channel, ref, event in itertools.product(
                ("stable", "dev", "unknown"),
                ("refs/heads/main", "refs/heads/feature", "refs/tags/v1"),
                ("schedule", "workflow_dispatch", "workflow_run", "pull_request")):
            expected = channel == "stable" and ref == "refs/heads/main" and event in (
                "schedule", "workflow_dispatch")
            self.assertEqual(sccache_cache.cache_write_allowed(channel, ref, event), expected)

    def test_retention_is_scoped_and_keeps_newest_two(self):
        caches = [snapshot(i) for i in (3, 1, 4, 2)] + [
            snapshot(5, ref="refs/heads/feature"), snapshot(6, key="unrelated-cache"),
            snapshot(7, key=sccache_cache.CACHE_PREFIX + "unexpected")]
        self.assertEqual(sccache_cache.snapshots_to_delete(caches), [2, 1])
        self.assertEqual(sccache_cache.snapshots_to_delete(caches[:1]), [])

    def test_invalid_owned_metadata_fails_closed(self):
        for extra in ({"id": True}, {"id": 0}, {"created_at": "bad"},
                      {"created_at": "2026-10-01T00:00:00"}):
            with self.assertRaises(ValueError):
                sccache_cache.snapshots_to_delete([snapshot(1, **extra)])

    @mock.patch.dict(os.environ, {"ANGLE_CACHE_CHANNEL": "dev",
                                 "GITHUB_REF": "refs/heads/main",
                                 "GITHUB_EVENT_NAME": "workflow_dispatch"})
    @mock.patch("sccache_cache.subprocess.check_output")
    @mock.patch("sccache_cache.subprocess.run")
    def test_dev_never_accesses_mutation_api(self, delete, listing):
        sccache_cache.prune()
        delete.assert_not_called()
        listing.assert_not_called()

    @mock.patch.dict(os.environ, {"ANGLE_CACHE_CHANNEL": "stable",
                                 "GITHUB_REF": "refs/heads/main",
                                 "GITHUB_EVENT_NAME": "schedule",
                                 "GITHUB_REPOSITORY": "owner/repo"})
    @mock.patch("sccache_cache.subprocess.check_output")
    @mock.patch("sccache_cache.subprocess.run")
    def test_paginated_prune(self, delete, listing):
        listing.return_value = json.dumps([
            {"actions_caches": [snapshot(1), snapshot(2)]},
            {"actions_caches": [snapshot(3)]}])
        sccache_cache.prune()
        delete.assert_called_once_with([
            "gh", "api", "--method", "DELETE", "repos/owner/repo/actions/caches/1"], check=True)

    def test_gn_wrapper_quoting_and_pilot_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(platform="win32", arch="arm64",
                cc_wrapper="C:/Program Files/sccache/sccache.exe", output=f"{temp}/args.gn",
                json_output=f"{temp}/args.json")
            with contextlib.redirect_stdout(io.StringIO()):
                angle_ci.write_gn_args(args)
            config = json.loads(Path(args.json_output).read_text())
            self.assertEqual(config["cc_wrapper"], '"C:/Program Files/sccache/sccache.exe"')
            self.assertFalse(config["use_siso"])
            self.assertIn('cc_wrapper = "\\"C:/Program Files/sccache/sccache.exe\\""',
                          Path(args.output).read_text())
            for args.platform, args.arch in (("win32", "x64"), ("linux", "arm64")):
                with self.assertRaises(ValueError):
                    angle_ci.write_gn_args(args)
            args.platform, args.arch = "win32", "arm64"
            args.cc_wrapper = 'C:/bad"path'
            with self.assertRaises(ValueError):
                angle_ci.write_gn_args(args)
            args.cc_wrapper = ""
            with contextlib.redirect_stdout(io.StringIO()):
                angle_ci.write_gn_args(args)
            config = json.loads(Path(args.json_output).read_text())
            self.assertNotIn("cc_wrapper", config)
            self.assertNotIn("use_siso", config)


if __name__ == "__main__":
    unittest.main()
