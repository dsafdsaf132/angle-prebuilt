#!/usr/bin/env python3
#
# Copyright 2026 The ANGLE Project Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Select the newest upstream ANGLE commit with successful post-submit CI."""

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ANGLE_CI_PROJECT = "angle"
ANGLE_CI_BUCKET = "ci"
BUILDBUCKET_SEARCH_URL = (
    "https://cr-buildbucket.appspot.com/prpc/buildbucket.v2.Builds/SearchBuilds"
)
UPSTREAM_COMMIT_PATTERN = re.compile(
    r"^Upstream-ANGLE-Commit:\s*([0-9a-f]{40})\s*$", re.MULTILINE
)
UPSTREAM_HOST = "chromium.googlesource.com"
UPSTREAM_PROJECT = "angle/angle"
XSSI_PREFIX = ")]}'"


def run_git(source_root, *args):
    result = subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def latest_synced_upstream_commit(source_root):
    messages = run_git(source_root, "log", "--format=%B%x00", "--max-count=1000")
    for message in messages.split("\0"):
        match = UPSTREAM_COMMIT_PATTERN.search(message)
        if match:
            return match.group(1)
    raise RuntimeError("Could not find an Upstream-ANGLE-Commit marker in fork history")


def commits_after(source_root, upstream_head, last_synced_commit, max_candidates):
    is_ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "merge-base",
            "--is-ancestor",
            last_synced_commit,
            upstream_head,
        ],
        check=False,
    )
    if is_ancestor.returncode != 0:
        raise RuntimeError(
            "The last synced upstream commit is not an ancestor of the requested upstream ref"
        )

    commits = run_git(
        source_root,
        "rev-list",
        "--first-parent",
        upstream_head,
        f"^{last_synced_commit}",
    ).splitlines()
    if len(commits) > max_candidates:
        print(
            f"Found {len(commits)} unreviewed upstream commits; checking the newest "
            f"{max_candidates} only"
        )
        return commits[:max_candidates]
    return commits


def decode_response(payload, grpc_code=None):
    if grpc_code not in (None, "0"):
        raise RuntimeError(f"Buildbucket pRPC returned gRPC code {grpc_code}")
    if payload.startswith(XSSI_PREFIX):
        _, _, payload = payload.partition("\n")
    response = json.loads(payload)
    if not isinstance(response, dict):
        raise RuntimeError("Buildbucket returned a non-object JSON response")
    if "error" in response:
        raise RuntimeError(f"Buildbucket returned an error response: {response['error']}")
    return response


def request_json(url, payload, attempts=5):
    request_data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=request_data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "angle-prebuilt-sync/1.0",
        },
        method="POST",
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return decode_response(
                    response.read().decode("utf-8"), response.headers.get("X-Prpc-Grpc-Code")
                )
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RuntimeError,
        ) as error:
            if attempt == attempts:
                raise RuntimeError(
                    f"Buildbucket request failed after {attempts} attempts: {error}"
                ) from error
            print(f"Buildbucket request failed on attempt {attempt}; retrying: {error}")
            time.sleep(attempt * 5)


def ci_builds_for_commit(commit, request=request_json):
    buildset = f"commit/gitiles/{UPSTREAM_HOST}/{UPSTREAM_PROJECT}/+/{commit}"
    response = request(
        BUILDBUCKET_SEARCH_URL,
        {
            "predicate": {
                "builder": {"project": ANGLE_CI_PROJECT, "bucket": ANGLE_CI_BUCKET},
                "tags": [{"key": "buildset", "value": buildset}],
            },
            "pageSize": 1000,
        },
    )
    if response.get("nextPageToken"):
        raise RuntimeError(f"Buildbucket returned more than one page for upstream commit {commit}")
    return response.get("builds", [])


def classify_ci_builds(builds):
    statuses = {build.get("status", "UNKNOWN") for build in builds}
    if not builds:
        return "pending", statuses
    if statuses == {"SUCCESS"}:
        return "success", statuses
    if statuses & {"FAILURE", "INFRA_FAILURE", "CANCELED", "EXPIRED"}:
        return "failed", statuses
    return "pending", statuses


def select_upstream_commit(commits, query_builds=ci_builds_for_commit):
    for commit in commits:
        builds = query_builds(commit)
        state, statuses = classify_ci_builds(builds)
        status_summary = ",".join(sorted(statuses)) if statuses else "none"
        print(f"Upstream CI {commit}: {state} ({len(builds)} builds; {status_summary})")
        if state == "success":
            return commit, len(builds)
    return "", 0


def write_result(path, commit, build_count):
    Path(path).write_text(
        f"selected_upstream_commit={commit}\nselected_ci_build_count={build_count}\n",
        encoding="utf-8",
    )


def self_test():
    assert decode_response(")]}'\n{\"builds\": []}", "0") == {"builds": []}
    try:
        decode_response('{"error": {"code": 13}}', "0")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Buildbucket error response was accepted")
    assert classify_ci_builds([]) == ("pending", set())
    assert classify_ci_builds([{"status": "SUCCESS"}]) == ("success", {"SUCCESS"})
    assert classify_ci_builds([{"status": "SUCCESS"}, {"status": "STARTED"}]) == (
        "pending",
        {"SUCCESS", "STARTED"},
    )
    assert classify_ci_builds([{"status": "FAILURE"}, {"status": "SUCCESS"}]) == (
        "failed",
        {"FAILURE", "SUCCESS"},
    )

    results = {
        "newest": [{"status": "STARTED"}],
        "failed": [{"status": "FAILURE"}],
        "green": [{"status": "SUCCESS"}, {"status": "SUCCESS"}],
    }
    selected, count = select_upstream_commit(
        ["newest", "failed", "green"], query_builds=results.__getitem__
    )
    assert selected == "green"
    assert count == 2
    print("self-test ok")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--upstream-head")
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--max-candidates", type=int, default=250)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.source_root or not args.upstream_head or not args.result_file:
        parser.error("--source-root, --upstream-head, and --result-file are required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.upstream_head):
        parser.error("--upstream-head must be a 40-character lowercase SHA")
    if args.max_candidates < 1:
        parser.error("--max-candidates must be positive")

    last_synced = latest_synced_upstream_commit(args.source_root)
    commits = commits_after(args.source_root, args.upstream_head, last_synced, args.max_candidates)
    print(f"Last synced upstream commit: {last_synced}")
    print(f"Upstream commits to evaluate: {len(commits)}")
    selected, build_count = select_upstream_commit(commits)
    if selected:
        print(f"Selected upstream commit: {selected} ({build_count} successful CI builds)")
    else:
        print("No unmerged upstream commit has completed successful ANGLE CI")
    write_result(args.result_file, selected, build_count)


if __name__ == "__main__":
    main()
