# ANGLE Prebuilt

This repository tracks upstream ANGLE and publishes ready-to-use archives for
native EGL/OpenGL ES consumers.

It syncs, builds, and releases every Sunday at 00:00 UTC.

## Targets

| Target | Archive |
| --- | --- |
| Linux x64 | `angle-{version}-linux-x64.tar.gz` |
| Linux arm64 | `angle-{version}-linux-arm64.tar.gz` |
| macOS arm64 | `angle-{version}-darwin-arm64.tar.gz` |
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

## License

ANGLE is distributed under the BSD-style license in `LICENSE`.

Redistributed archives include `LICENSE`. Review third-party and platform
runtime redistribution terms for files included by each build, especially
`d3dcompiler_47.dll` on Windows.
