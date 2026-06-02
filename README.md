# ANGLE Prebuilt

This repository is a fork of Google ANGLE focused on producing cross-platform
prebuilt shared-library archives for native EGL/OpenGL ES/WebGL-style consumers.

## Targets

| Target | Archive |
| --- | --- |
| Linux x64 | `angle-{version}-linux-x64.tar.gz` |
| Linux arm64 | `angle-{version}-linux-arm64.tar.gz` |
| macOS x64 | `angle-{version}-darwin-x64.tar.gz` |
| macOS arm64 | `angle-{version}-darwin-arm64.tar.gz` |
| macOS universal | `angle-{version}-darwin-universal.tar.gz` |
| Windows x64 | `angle-{version}-win32-x64.zip` |
| Windows arm64 | `angle-{version}-win32-arm64.zip` |

## Archive Layout

```text
angle/
  include/
    EGL/
    GLES/
    GLES2/
    GLES3/
    KHR/
  out/
    Release/
      libEGL.*
      libGLESv2.*
      platform-specific import/runtime files
  LICENSE
  angle-build.json
```

`angle-build.json` records the ANGLE ref, resolved commit, platform, arch,
Release/shared-library settings, generation time, and GN args.

## Build And Release

Use the **ANGLE Prebuilt** GitHub Actions workflow.

Inputs:

| Input | Default | Description |
| --- | --- | --- |
| `angle_ref` | `main` | ANGLE branch, tag, or ref to build |
| `angle_commit` | empty | Optional exact ANGLE commit |
| `release_tag` | empty | Optional GitHub Release tag override |
| `artifact_run_id` | empty | Optional workflow run ID to reuse existing artifacts |

Push and pull request runs do lightweight CI helper validation only. Manual and
scheduled runs build, verify, and publish release assets by default using the
ANGLE commit position.

Set `artifact_run_id` in a manual run to skip rebuilding and publish from a
previous run's `angle-*` artifacts.

The scheduled run builds upstream ANGLE `main` every Sunday at 00:00 UTC and
publishes `angle-main-{commitPosition}`.

The **Sync Fork** workflow updates the fork from upstream ANGLE `main` every
Saturday at 23:00 UTC.

## License

ANGLE is distributed under the BSD-style license in `LICENSE`.

Redistributed archives include `LICENSE`. Review third-party and platform
runtime redistribution terms for files included by each build, especially
`d3dcompiler_47.dll` on Windows.
