#!/usr/bin/env python3
"""Retention for the Windows ARM64 compiler-cache pilot only."""

import argparse
import datetime
import json
import os
import re
import subprocess


CACHE_PREFIX = "sccache-v1-win32-arm64-"
CACHE_REF = "refs/heads/main"
KEEP_SNAPSHOTS = 2


def cache_write_allowed(channel, ref, event):
    return (channel == "stable" and ref == CACHE_REF and
            event in ("schedule", "workflow_dispatch"))


def snapshots_to_delete(caches):
    owned = []
    for cache in caches:
        if (cache.get("ref") != CACHE_REF or
                not re.fullmatch(re.escape(CACHE_PREFIX) + r"\d+-\d+", cache.get("key", ""))):
            continue
        cache_id = cache.get("id")
        if type(cache_id) is not int or cache_id <= 0:
            raise ValueError("Invalid cache ID; refusing deletion")
        created = datetime.datetime.fromisoformat(cache["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("Cache creation time must include a timezone")
        owned.append((created, cache_id))
    owned.sort(reverse=True)
    return [cache_id for _, cache_id in owned[KEEP_SNAPSHOTS:]]


def prune():
    if not cache_write_allowed(os.environ.get("ANGLE_CACHE_CHANNEL"),
                               os.environ.get("GITHUB_REF"),
                               os.environ.get("GITHUB_EVENT_NAME")):
        print("Compiler cache is read-only; no snapshots will be deleted")
        return
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    endpoint = f"repos/{repository}/actions/caches"
    result = subprocess.check_output([
        "gh", "api", "--method", "GET", endpoint, "--paginate", "--slurp",
        "-f", f"key={CACHE_PREFIX}", "-f", f"ref={CACHE_REF}", "-F", "per_page=100"
    ], text=True)
    caches = [cache for page in json.loads(result) for cache in page["actions_caches"]]
    for cache_id in snapshots_to_delete(caches):
        print(f"Deleting old compiler cache snapshot {cache_id}")
        subprocess.run(["gh", "api", "--method", "DELETE", f"{endpoint}/{cache_id}"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prune",))
    parser.parse_args()
    prune()
