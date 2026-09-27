#!/usr/bin/env python3
"""Resolve channel metadata and validate versioned ANGLE release archives."""

import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


RELEASES_URL = "https://chromiumdash.appspot.com/fetch_releases"
DEPS_URL = "https://chromium.googlesource.com/chromium/src/+/{}/DEPS?format=TEXT"
ANGLE_URL = "https://chromium.googlesource.com/angle/angle/+/{}/"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ANGLE-Prebuilt-CI/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def resolve_stable():
    query = urllib.parse.urlencode(
        {"channel": "Stable", "platform": "Windows", "num": 1}
    )
    releases = json.loads(fetch(f"{RELEASES_URL}?{query}"))
    if not releases or releases[0].get("channel") != "Stable":
        raise RuntimeError("ChromiumDash returned no Windows Stable release")
    release = releases[0]
    version = release.get("version", "")
    chromium = release.get("hashes", {}).get("chromium", "")
    angle = release.get("hashes", {}).get("angle", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise RuntimeError(f"Invalid Chrome Stable version: {version!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", chromium):
        raise RuntimeError(f"Invalid Stable Chromium commit: {chromium!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", angle):
        raise RuntimeError(f"Invalid Stable ANGLE commit: {angle!r}")

    deps = fetch(DEPS_URL.format(chromium)).decode("ascii")
    import base64

    deps = base64.b64decode(deps).decode("utf-8")
    angle_entry = re.search(
        r"['\"]src/third_party/angle['\"]\s*:\s*([^\n]+)", deps
    )
    angle_revision = re.search(
        r"['\"]angle_revision['\"]\s*:\s*['\"]([0-9a-f]{40})['\"]", deps
    )
    if (
        not angle_entry
        or "angle_revision" not in angle_entry.group(1)
        or not angle_revision
        or angle_revision.group(1) != angle
    ):
        raise RuntimeError(
            f"Chrome {version} DEPS ANGLE pin does not match ChromiumDash SHA {angle}"
        )

    date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    sha7 = angle[:7]
    tag = f"angle-stable-chrome-{version}-{sha7}"
    return {
        "schemaVersion": 1,
        "channel": "stable",
        "releaseTag": tag,
        "releaseTitle": f"Stable · Chrome {version} · ANGLE {sha7}",
        "releaseDate": date,
        "angleRef": "upstream",
        "angleCommit": angle,
        "upstreamCommit": angle,
        "workflowCommit": os.environ["GITHUB_SHA"],
        "tagCommit": os.environ["GITHUB_SHA"],
        "chromeVersion": version,
        "chromiumCommit": chromium,
        "sourceUrl": ANGLE_URL.format(angle),
    }


def resolve_dev(args):
    angle_commit = args["angle_commit"]
    upstream_commit = args["upstream_commit"]
    workflow_commit = os.environ["GITHUB_SHA"]
    for label, value in (("fork", angle_commit), ("upstream", upstream_commit)):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise RuntimeError(f"Invalid {label} ANGLE SHA: {value!r}")
    date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    tag = f"angle-dev-{date}-{upstream_commit[:7]}"
    return {
        "schemaVersion": 1,
        "channel": "dev",
        "releaseTag": tag,
        "releaseTitle": f"Dev · {date} · ANGLE {upstream_commit[:7]}",
        "releaseDate": date,
        "angleRef": args["angle_ref"],
        "angleCommit": angle_commit,
        "upstreamCommit": upstream_commit,
        "workflowCommit": workflow_commit,
        "tagCommit": workflow_commit,
        "chromeVersion": "",
        "chromiumCommit": "",
        "sourceUrl": ANGLE_URL.format(upstream_commit),
    }


def release_asset_names(manifest):
    tag = manifest["releaseTag"]
    return sorted(
        f"{tag}-{suffix}" + (".zip" if suffix.startswith("win32-") else ".tar.gz")
        for suffix in (
            "linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64",
            "darwin-universal", "win32-x64", "win32-arm64",
        )
    )


def validate(manifest, archive_metadata):
    expected = {
        (platform, arch)
        for platform, arch in (
            ("linux", "x64"), ("linux", "arm64"), ("darwin", "x64"),
            ("darwin", "arm64"), ("darwin", "universal"), ("win32", "x64"),
            ("win32", "arm64"),
        )
    }
    if len(archive_metadata) != len(expected):
        raise RuntimeError(f"Expected 7 release archives, found {len(archive_metadata)}")
    actual = set()
    for metadata in archive_metadata:
        target = (metadata.get("platform"), metadata.get("arch"))
        actual.add(target)
        for key in ("channel", "upstreamCommit", "workflowCommit"):
            if metadata.get(key) != manifest.get(key):
                raise RuntimeError(f"Archive provenance mismatch for {key}: {metadata.get(key)!r}")
        if metadata.get("angleCommit") != manifest.get("angleCommit"):
            raise RuntimeError("Release archives contain different ANGLE source commits")
    if actual != expected:
        raise RuntimeError(f"Release target set mismatch: {sorted(actual)!r}")


def github_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ANGLE-Prebuilt-CI/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def has_stable_release(repository, upstream_commit):
    page = 1
    while True:
        releases = github_json(
            f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"
        )
        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue
            match = re.search(r"^ANGLE-RELEASE-MANIFEST=(\{.*\})$", release.get("body", ""), re.MULTILINE)
            if match:
                recorded = json.loads(match.group(1))
                if recorded.get("channel") == "stable" and recorded.get("upstreamCommit") == upstream_commit:
                    return True
        if len(releases) < 100:
            return False
        page += 1


def make_release_notes(manifest, artifact_root):
    from pathlib import Path

    names = sorted(path.name for path in Path(artifact_root).iterdir() if path.is_file())
    body = [
        f"Release: {manifest['releaseTitle']}",
        f"Tag: `{manifest['releaseTag']}`",
        "",
        f"Channel: {manifest['channel']}",
        f"Upstream ANGLE: `{manifest['upstreamCommit']}`",
        f"Source: {manifest['sourceUrl']}",
        f"Workflow commit: `{manifest['workflowCommit']}`",
    ]
    if manifest.get("chromeVersion"):
        body.extend(
            [
                f"Chrome version: `{manifest['chromeVersion']}`",
                f"Chromium commit: `{manifest['chromiumCommit']}`",
            ]
        )
    body.extend(["", "Assets:", *(f"- `{name}`" for name in names), ""])
    body.append("ANGLE-RELEASE-MANIFEST=" + json.dumps(manifest, sort_keys=True))
    return "\n".join(body) + "\n"


def main():
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("resolve-stable")
    dev = commands.add_parser("resolve-dev")
    dev.add_argument("--angle-ref", required=True)
    dev.add_argument("--angle-commit", required=True)
    dev.add_argument("--upstream-commit", required=True)
    stable_check = commands.add_parser("has-stable-release")
    stable_check.add_argument("--repository", required=True)
    stable_check.add_argument("--upstream-commit", required=True)
    notes = commands.add_parser("release-notes")
    notes.add_argument("--manifest", required=True)
    notes.add_argument("--artifact-root", required=True)
    notes.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "resolve-stable":
        manifest = resolve_stable()
        print(json.dumps(manifest, sort_keys=True))
    elif args.command == "resolve-dev":
        manifest = resolve_dev(vars(args))
        print(json.dumps(manifest, sort_keys=True))
    elif args.command == "has-stable-release":
        print("true" if has_stable_release(args.repository, args.upstream_commit) else "false")
    else:
        from pathlib import Path

        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        Path(args.output).write_text(
            make_release_notes(manifest, args.artifact_root), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
