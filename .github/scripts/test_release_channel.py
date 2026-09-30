#!/usr/bin/env python3
"""Regression checks for Stable channel selection."""

import unittest

from release_channel import select_stable_release, select_stable_version


def history_release(version, fraction=1, end_time=None):
    record = {
        "name": f"chrome/platforms/win/channels/stable/versions/{version}/releases/1",
        "version": version,
        "fraction": fraction,
        "serving": {"startTime": "2026-09-29T18:30:43Z"},
    }
    if end_time:
        record["serving"]["endTime"] = end_time
    return record


def release(version, channel="Stable", platform="Windows"):
    return {"version": version, "channel": channel, "platform": platform}


class StableSelectionTests(unittest.TestCase):
    def test_limited_rollout_does_not_override_general_stable(self):
        version = select_stable_version({"releases": [
            history_release("155.0.8059.12", fraction=0.005),
            history_release("154.0.8037.93"),
            history_release("154.0.8037.92", fraction=0.2475),
        ]})
        self.assertEqual(version, "154.0.8037.93")
        expected = release(version)
        self.assertIs(select_stable_release(version, [
            release("155.0.8059.12"), release("154.0.8037.92"), expected,
        ]), expected)

    def test_full_rollout_promotion_allows_new_milestone(self):
        self.assertEqual(select_stable_version({"releases": [
            history_release("154.0.8037.93"), history_release("155.0.8059.12"),
        ]}), "155.0.8059.12")

    def test_ended_rollout_is_excluded_and_versions_sort_numerically(self):
        self.assertEqual(select_stable_version({"releases": [
            history_release("155.0.8059.12", end_time="2026-09-29T19:00:00Z"),
            history_release("154.0.8037.99"), history_release("154.0.8037.100"),
        ]}), "154.0.8037.100")

    def test_missing_or_unverified_history_fails(self):
        wrong_channel = history_release("155.0.8059.12")
        wrong_channel["name"] = wrong_channel["name"].replace("stable", "beta")
        missing_serving = history_release("154.0.8037.93")
        missing_serving.pop("serving")
        for records in ([], [history_release("155.0.8059.12", 0.005)],
                        [wrong_channel], [missing_serving], [history_release("invalid")]):
            with self.subTest(records=records):
                with self.assertRaisesRegex(RuntimeError, "no active fully rolled-out"):
                    select_stable_version({"releases": records})

    def test_exact_version_channel_and_platform_required(self):
        records = [release("154.0.8037.92"), release("154.0.8037.94"),
                   release("154.0.8037.93", channel="Beta"),
                   release("154.0.8037.93", platform="Mac")]
        with self.assertRaisesRegex(RuntimeError, "matching verified"):
            select_stable_release("154.0.8037.93", records)


if __name__ == "__main__":
    unittest.main()
