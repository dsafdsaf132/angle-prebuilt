# ANGLE Prebuilt

This repository tracks upstream [google/ANGLE](https://github.com/google/angle) and publishes ready-to-use archives for
native EGL/OpenGL ES consumers.

Stable builds follow Chrome Stable and run daily. Dev builds follow upstream and run weekly after the Sunday 00:00 UTC sync.

Stable selection uses VersionHistory to select the newest Windows Stable version
that is currently served at 100% rollout. Limited rollout experiments are excluded.
ChromiumDash supplies the Chromium and ANGLE commits for that exact version;
resolution fails if a matching release cannot be found.

Each archive records the full upstream SHA in `angle-build.json`.

Archive filenames use the first 7 characters of the upstream SHA.

## Targets

| Target | Archive | CI |
| --- | --- | --- |
| Linux x64 | `angle-{sha}-linux-x64.tar.gz` | [![Smoke passed][smoke-passed]][ci-workflow] |
| Linux arm64 | `angle-{sha}-linux-arm64.tar.gz` | [![Smoke passed][smoke-passed]][ci-workflow] |
| macOS x64 | `angle-{sha}-darwin-x64.tar.gz` | [![Smoke skipped][smoke-skipped]][ci-workflow] |
| macOS arm64 | `angle-{sha}-darwin-arm64.tar.gz` | [![Smoke passed][smoke-passed]][ci-workflow] |
| macOS universal | `angle-{sha}-darwin-universal.tar.gz` | [![Smoke skipped][smoke-skipped]][ci-workflow] |
| Windows x64 | `angle-{sha}-win32-x64.zip` | [![Smoke passed][smoke-passed]][ci-workflow] |
| Windows arm64 | `angle-{sha}-win32-arm64.zip` | [![Smoke passed][smoke-passed]][ci-workflow] |

[ci-workflow]: https://github.com/dsafdsaf132/angle-prebuilt/actions/workflows/build.yml
[smoke-passed]: https://img.shields.io/badge/Smoke-passed-brightgreen
[smoke-skipped]: https://img.shields.io/badge/Smoke-skipped-lightgrey

## Software Rendering

Builds include the Vulkan backend and SwiftShader for CPU rendering. Existing
OpenGL, Metal, and Direct3D backends remain available. The Vulkan loader is
linked into ANGLE on Linux/macOS and bundled as `vulkan-1.dll` on Windows;
no system Vulkan loader is required.

To select SwiftShader, pass `EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE` as
`EGL_PLATFORM_ANGLE_TYPE_ANGLE` and
`EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE` as
`EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE` to `eglGetPlatformDisplayEXT`. Keep the
SwiftShader library and `vk_swiftshader_icd.json` beside the ANGLE libraries.
On Linux, also set `EGL_PLATFORM_ANGLE_NATIVE_PLATFORM_TYPE_ANGLE` to
`EGL_PLATFORM_SURFACELESS_MESA` for rendering without an X display.
CI checks SwiftShader clear/readback separately from the existing backend smoke.

Before Windows builds, the CI helper patches the checked-out ANGLE build definition
to use the SwiftShader ICD basename without a leading `.\` component. This keeps
ICD lookup compatible with extended-length DLL paths used by Node.js. The patch
is applied only in the build checkout; upstream source files are not changed in
this repository. Unexpected upstream definitions fail the build instead of being
patched blindly.

## Compiler Cache Pilot

Windows ARM64 uses sccache 0.18.0 with Ninja. The local cache lives in
`RUNNER_TEMP/sccache`, with a 2 GiB object-cache budget. Direct/preprocessor
caching is disabled to avoid a separate LRU budget. GitHub Actions Cache stores snapshots
under `sccache-v1-win32-arm64-{run_id}-{run_attempt}`; builds restore the newest
matching snapshot without partitioning by source commit or release channel.

Only main-branch stable builds triggered by schedule or manual dispatch write
the cache. Dev builds use local read-only mode and never save or delete shared
snapshots; cache misses still compile normally. Consequently, dev cannot warm
an empty cache. A separate stable-only retention job keeps the newest two main
snapshots, leaving other caches untouched. Cache restore/save/cleanup failures
do not fail releases. GitHub's repository quota and inactivity eviction still
apply. Build summaries report cache mode, restored key, hits, misses, and size.

The pilot needs a cold stable build followed by a warm stable build to measure
actual speedup. Other targets are unchanged; compiler caching does not skip
linking, packaging, or smoke tests.

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
      *vk_swiftshader.*
      vk_swiftshader_icd.json
      platform-specific import/runtime files
  LICENSE
  SWIFTSHADER_LICENSE.txt
  VULKAN_LOADER_LICENSE.txt (Windows)
  angle-build.json
```

`angle-build.json` records the ANGLE ref, resolved commit, platform, arch,
Release/shared-library settings, generation time, and GN args.

## License

ANGLE is distributed under the BSD-style license in `LICENSE`.

Redistributed archives include `LICENSE`. Review third-party and platform
runtime redistribution terms for files included by each build, especially
`d3dcompiler_47.dll` on Windows.
