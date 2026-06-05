# ANGLE Prebuilt

This repository tracks upstream ANGLE and publishes ready-to-use archives for
native EGL/OpenGL ES consumers.

It syncs, builds, and releases every Sunday at 00:00 UTC.

## Targets

| Target | Archive | CI |
| --- | --- | --- |
| Linux x64 | `angle-{version}-linux-x64.tar.gz` | [![linux-x64][ci-linux-x64]][ci-workflow] |
| Linux arm64 | `angle-{version}-linux-arm64.tar.gz` | [![linux-arm64][ci-linux-arm64]][ci-workflow] |
| macOS x64 | `angle-{version}-darwin-x64.tar.gz` | [![macos-x64][ci-macos-x64]][ci-workflow] |
| macOS arm64 | `angle-{version}-darwin-arm64.tar.gz` | [![macos-arm64][ci-macos-arm64]][ci-workflow] |
| Windows x64 | `angle-{version}-win32-x64.zip` | [![windows-x64][ci-windows-x64]][ci-workflow] |
| Windows arm64 | `angle-{version}-win32-arm64.zip` | [![windows-arm64][ci-windows-arm64]][ci-workflow] |

[ci-workflow]: https://github.com/dsafdsaf132/angle/actions/workflows/angle-prebuilt.yml
[ci-linux-x64]: https://img.shields.io/github/actions/workflow/status/dsafdsaf132/angle/angle-prebuilt.yml?branch=main&job=linux-x64&label=linux-x64
[ci-linux-arm64]: https://img.shields.io/github/actions/workflow/status/dsafdsaf132/angle/angle-prebuilt.yml?branch=main&job=linux-arm64&label=linux-arm64
[ci-macos-x64]: https://img.shields.io/github/actions/workflow/status/dsafdsaf132/angle/angle-prebuilt.yml?branch=main&job=macos-x64&label=macos-x64
[ci-macos-arm64]: https://img.shields.io/github/actions/workflow/status/dsafdsaf132/angle/angle-prebuilt.yml?branch=main&job=macos-arm64&label=macos-arm64
[ci-windows-x64]: https://img.shields.io/github/actions/workflow/status/dsafdsaf132/angle/angle-prebuilt.yml?branch=main&job=windows-x64&label=windows-x64
[ci-windows-arm64]: https://img.shields.io/github/actions/workflow/status/dsafdsaf132/angle/angle-prebuilt.yml?branch=main&job=windows-arm64&label=windows-arm64

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

## License

ANGLE is distributed under the BSD-style license in `LICENSE`.

Redistributed archives include `LICENSE`. Review third-party and platform
runtime redistribution terms for files included by each build, especially
`d3dcompiler_47.dll` on Windows.
