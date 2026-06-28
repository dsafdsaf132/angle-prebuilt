#!/usr/bin/env python3
#
# Copyright 2026 The ANGLE Project Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


HEADER_DIRS = ("EGL", "GLES", "GLES2", "GLES3", "KHR")
RELEASE_DIR = Path("angle") / "out" / "Release"

COMMON_GN_ARGS = {
    "is_debug": False,
    "is_component_build": False,
    "angle_use_static_angle": False,
    "angle_build_all": False,
    "angle_build_tests": False,
    "build_angle_deqp_tests": False,
    "build_angle_end2end_tests_library": False,
    "angle_enable_cl": False,
    "angle_enable_null": False,
    "angle_enable_renderdoc": False,
    "angle_enable_swiftshader": False,
    "angle_enable_trace": False,
    "angle_enable_vulkan": False,
    "angle_enable_vulkan_api_dump_layer": False,
    "angle_enable_vulkan_validation_layers": False,
    "angle_enable_wgpu": False,
    "angle_with_capture_by_default": False,
    "clang_use_chrome_plugins": False,
    "symbol_level": 0,
    "treat_warnings_as_errors": False,
}

PLATFORM_GN_ARGS = {
    "linux": {
        "target_os": "linux",
        "angle_enable_d3d9": False,
        "angle_enable_d3d11": False,
        "angle_enable_gl": True,
        "angle_enable_gl_desktop_backend": True,
        "angle_enable_glsl": True,
        "angle_enable_essl": True,
        "angle_enable_hlsl": False,
        "angle_enable_metal": False,
        "angle_enable_msl": False,
        "angle_use_vulkan_display": False,
        "angle_use_wayland": False,
        "angle_use_x11": True,
        "ozone_platform_drm": False,
        "ozone_platform_headless": False,
        "ozone_platform_wayland": False,
        "ozone_platform_x11": False,
        "use_ozone": False,
    },
    "darwin": {
        "target_os": "mac",
        "angle_enable_cgl": False,
        "angle_enable_d3d9": False,
        "angle_enable_d3d11": False,
        "angle_enable_essl": False,
        "angle_enable_gl": False,
        "angle_enable_glsl": False,
        "angle_enable_hlsl": False,
        "angle_enable_metal": True,
        "angle_enable_msl": True,
    },
    "win32": {
        "target_os": "win",
        "angle_enable_d3d9": False,
        "angle_enable_d3d11": True,
        "angle_enable_d3d11_compositor_native_window": False,
        "angle_enable_essl": False,
        "angle_enable_gl": False,
        "angle_enable_glsl": False,
        "angle_enable_hlsl": True,
        "angle_enable_metal": False,
        "angle_enable_msl": False,
    },
}


SMOKE_SOURCE = r"""
#define EGL_EGLEXT_PROTOTYPES 1
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <EGL/eglext_angle.h>
#include <GLES3/gl3.h>
#include <cstdio>
#include <cstdlib>

static void fail(const char *message)
{
    std::fprintf(stderr, "%s (EGL error 0x%04x)\n", message, eglGetError());
    std::exit(1);
}

static EGLDisplay getAnglePlatformDisplay()
{
#if defined(_WIN32)
    const EGLint displayAttribs[] = {
        EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_D3D11_ANGLE,
        EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_DEVICE_TYPE_D3D_WARP_ANGLE,
        EGL_NONE,
    };
#elif defined(__APPLE__)
    const EGLint displayAttribs[] = {
        EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_METAL_ANGLE,
        EGL_NONE,
    };
#elif defined(__linux__)
    const EGLint displayAttribs[] = {
        EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_OPENGL_ANGLE,
        EGL_NONE,
    };
#else
    const EGLint displayAttribs[] = {EGL_NONE};
#endif

    return eglGetPlatformDisplayEXT(EGL_PLATFORM_ANGLE_ANGLE,
                                    reinterpret_cast<void *>(EGL_DEFAULT_DISPLAY),
                                    displayAttribs);
}

int main()
{
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);

    EGLint major = 0;
    EGLint minor = 0;
    if (display == EGL_NO_DISPLAY || !eglInitialize(display, &major, &minor))
    {
        display = getAnglePlatformDisplay();
        if (display == EGL_NO_DISPLAY)
        {
            if (std::getenv("ANGLE_SMOKE_ALLOW_NO_DISPLAY") != nullptr)
            {
                std::fprintf(stderr, "Skipping runtime smoke: no EGL display is available\n");
                return 0;
            }
            fail("eglGetDisplay/eglGetPlatformDisplayEXT failed");
        }
        if (!eglInitialize(display, &major, &minor))
        {
            fail("eglInitialize failed");
        }
    }

    EGLint configAttribs[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8,
        EGL_ALPHA_SIZE, 8,
        EGL_NONE,
    };

    EGLConfig config = nullptr;
    EGLint configCount = 0;
    if (!eglChooseConfig(display, configAttribs, &config, 1, &configCount) || configCount < 1)
    {
        fail("eglChooseConfig failed");
    }

    EGLint surfaceAttribs[] = {
        EGL_WIDTH, 16,
        EGL_HEIGHT, 16,
        EGL_NONE,
    };
    EGLSurface surface = eglCreatePbufferSurface(display, config, surfaceAttribs);
    if (surface == EGL_NO_SURFACE)
    {
        fail("eglCreatePbufferSurface failed");
    }

    EGLint contextAttribs[] = {
        EGL_CONTEXT_CLIENT_VERSION, 3,
        EGL_NONE,
    };
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttribs);
    if (context == EGL_NO_CONTEXT)
    {
        fail("eglCreateContext failed");
    }

    if (!eglMakeCurrent(display, surface, surface, context))
    {
        fail("eglMakeCurrent failed");
    }

    const GLubyte *version = glGetString(GL_VERSION);
    if (version == nullptr)
    {
        fail("glGetString(GL_VERSION) failed");
    }
    std::printf("GL_VERSION=%s\n", reinterpret_cast<const char *>(version));

    glViewport(0, 0, 16, 16);
    glClearColor(0.0f, 0.25f, 0.5f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    if (glGetError() != GL_NO_ERROR)
    {
        fail("glClear failed");
    }

    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroySurface(display, surface);
    eglDestroyContext(display, context);
    eglTerminate(display);
    return 0;
}
"""


def run(cmd, cwd=None, env=None, check=True):
    printable = " ".join(str(part) for part in cmd)
    print(f"+ {printable}", flush=True)
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, check=check)


def run_output(cmd, cwd=None, env=None, check=True):
    printable = " ".join(str(part) for part in cmd)
    print(f"+ {printable}", flush=True)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )
    print(result.stdout, end="")
    return result.stdout


def format_gn_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise TypeError(f"Unsupported GN value: {value!r}")


def write_gn_args(args):
    gn_args = dict(COMMON_GN_ARGS)
    gn_args.update(PLATFORM_GN_ARGS[args.platform])
    if args.platform == "linux" and args.arch == "arm64":
        gn_args["clang_base_path"] = "/usr/lib/llvm-23"
        gn_args["clang_version"] = "23"
        gn_args["is_clang"] = True
        gn_args["target_cpu"] = args.arch
        gn_args["use_sysroot"] = False
    else:
        gn_args["target_cpu"] = args.arch

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key} = {format_gn_value(gn_args[key])}" for key in sorted(gn_args)]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.json_output:
        json_output = Path(args.json_output)
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(gn_args, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(output.read_text(encoding="utf-8"))


def parse_angle_version(source_root, angle_ref):
    normalized_ref = (angle_ref or "").removeprefix("refs/heads/")
    try:
        position = subprocess.check_output(
            [
                "git",
                "log",
                "-1",
                "--format=%(trailers:key=Upstream-ANGLE-Commit-Position,valueonly)",
                "--grep=^Upstream-ANGLE-Commit-Position:",
                "HEAD",
            ],
            cwd=source_root,
            text=True,
        ).strip()
        if position:
            if normalized_ref == "main":
                return f"main-{position}"
            return position
    except subprocess.SubprocessError:
        pass

    try:
        message = subprocess.check_output(
            ["git", "log", "-1", "--format=%B", "HEAD"], cwd=source_root, text=True
        )
        footer = re.search(r"^Upstream-ANGLE-Commit-Position:\s*(\d+)\s*$", message, re.MULTILINE)
        if footer:
            version = footer.group(1)
            if normalized_ref == "main":
                return f"main-{version}"
            return version
    except subprocess.SubprocessError:
        pass

    try:
        sync_commit = subprocess.check_output(
            [
                "git",
                "log",
                "-1",
                "--format=%H",
                "--grep=^chore(sync): merge upstream ANGLE",
                "HEAD",
            ],
            cwd=source_root,
            text=True,
        ).strip()
        if sync_commit:
            upstream_parent = subprocess.check_output(
                ["git", "rev-parse", f"{sync_commit}^2"], cwd=source_root, text=True
            ).strip()
            version = subprocess.check_output(
                ["git", "rev-list", upstream_parent, "--count"], cwd=source_root, text=True
            ).strip()
            if version and version != "0":
                if normalized_ref == "main":
                    return f"main-{version}"
                return version
    except subprocess.SubprocessError:
        pass

    commit_id = Path(source_root) / "src" / "commit_id.py"
    if commit_id.exists():
        try:
            version = subprocess.check_output(
                [sys.executable, str(commit_id), "position"], cwd=source_root, text=True
            ).strip()
            if version and version != "0":
                if normalized_ref == "main":
                    return f"main-{version}"
                return version
        except subprocess.SubprocessError:
            pass

    match = re.search(r"(?:^|/)(\d{4,})(?:$|[-_/])", angle_ref or "")
    if match:
        return match.group(1)

    try:
        short_commit = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=source_root, text=True
        ).strip()
        if normalized_ref == "main":
            return f"main-{short_commit}"
        return short_commit
    except subprocess.SubprocessError:
        return "unknown"


def copy_header_dirs(source_root, package_root):
    include_src = Path(source_root) / "include"
    include_dst = package_root / "angle" / "include"
    include_dst.mkdir(parents=True, exist_ok=True)
    for header_dir in HEADER_DIRS:
        src = include_src / header_dir
        if not src.is_dir():
            raise FileNotFoundError(f"Missing include directory: {src}")
        shutil.copytree(src, include_dst / header_dir, dirs_exist_ok=True)


def copy_one(src, dst):
    if not src.exists():
        raise FileNotFoundError(f"Missing build output: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def maybe_copy(src, dst):
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


def copy_build_outputs(source_root, build_dir, package_root, target_platform):
    out_dst = package_root / RELEASE_DIR
    out_dst.mkdir(parents=True, exist_ok=True)
    build_dir = Path(build_dir)

    if target_platform == "linux":
        for name in ("libEGL.so", "libGLESv2.so"):
            copy_one(build_dir / name, out_dst / name)
        for pattern in ("libEGL.so.*", "libGLESv2.so.*"):
            for src in sorted(build_dir.glob(pattern)):
                if not src.name.endswith(".TOC"):
                    maybe_copy(src, out_dst / src.name)
    elif target_platform == "darwin":
        for name in ("libEGL.dylib", "libGLESv2.dylib"):
            copy_one(build_dir / name, out_dst / name)
        fix_macos_install_names(out_dst)
    elif target_platform == "win32":
        for name in ("libEGL.dll", "libGLESv2.dll"):
            copy_one(build_dir / name, out_dst / name)

        for base in ("libEGL", "libGLESv2"):
            import_lib = build_dir / f"{base}.lib"
            dll_import_lib = build_dir / f"{base}.dll.lib"
            if import_lib.exists():
                copy_one(import_lib, out_dst / f"{base}.lib")
                maybe_copy(dll_import_lib, out_dst / f"{base}.dll.lib")
            elif dll_import_lib.exists():
                copy_one(dll_import_lib, out_dst / f"{base}.dll.lib")
                copy_one(dll_import_lib, out_dst / f"{base}.lib")
            else:
                raise FileNotFoundError(f"Missing import library for {base}")

            maybe_copy(build_dir / f"{base}.pdb", out_dst / f"{base}.pdb")

        compiler = find_d3dcompiler(build_dir)
        if compiler:
            shutil.copy2(compiler, out_dst / "d3dcompiler_47.dll")
            print(f"Included {compiler}")
        else:
            print("d3dcompiler_47.dll was not found; continuing without it")
    else:
        raise ValueError(f"Unsupported platform: {target_platform}")


def find_d3dcompiler(build_dir):
    names = ("d3dcompiler_47.dll", "D3DCompiler_47.dll")
    for name in names:
        candidate = build_dir / name
        if candidate.exists():
            return candidate
    return None


def fix_macos_install_names(out_dir):
    if sys.platform != "darwin":
        return

    for name in ("libEGL.dylib", "libGLESv2.dylib"):
        lib = out_dir / name
        run(["install_name_tool", "-id", f"@rpath/{name}", str(lib)])

    egl = out_dir / "libEGL.dylib"
    deps = run_output(["otool", "-L", str(egl)])
    for line in deps.splitlines()[1:]:
        dep = line.strip().split(" ", 1)[0]
        if dep.endswith("/libGLESv2.dylib") or dep == "libGLESv2.dylib":
            run(["install_name_tool", "-change", dep, "@rpath/libGLESv2.dylib", str(egl)])


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_build_json(package_root, args, gn_args):
    metadata = {
        "angleRef": args.angle_ref,
        "angleCommit": args.angle_commit,
        "platform": args.platform,
        "arch": args.arch,
        "buildType": "Release",
        "shared": True,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "gnArgs": gn_args,
    }
    (package_root / "angle" / "angle-build.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def archive_name(version, target_platform, arch):
    if target_platform == "win32":
        return f"angle-{version}-{target_platform}-{arch}.zip"
    return f"angle-{version}-{target_platform}-{arch}.tar.gz"


def create_tar_gz(source_dir, archive_path):
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(source_dir.rglob("*")):
            arcname = path.relative_to(source_dir)
            info = archive.gettarinfo(path, arcname)
            info.mtime = 0
            if path.is_file():
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            else:
                archive.addfile(info)


def create_zip(source_dir, archive_path):
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            archive.write(path, path.relative_to(source_dir))


def create_package(args):
    source_root = Path(args.source_root).resolve()
    build_dir = Path(args.build_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    gn_args = load_json(args.gn_args_json)
    version = parse_angle_version(source_root, args.angle_ref)

    with tempfile.TemporaryDirectory() as temp:
        package_root = Path(temp) / "package"
        copy_header_dirs(source_root, package_root)
        copy_build_outputs(source_root, build_dir, package_root, args.platform)
        copy_one(source_root / "LICENSE", package_root / "angle" / "LICENSE")
        write_build_json(package_root, args, gn_args)

        name = archive_name(version, args.platform, args.arch)
        archive_path = artifact_dir / name
        if args.platform == "win32":
            create_zip(package_root, archive_path)
        else:
            create_tar_gz(package_root, archive_path)

    print(f"archive={archive_path}")
    print(f"version={version}")


def extract_archive(archive_path, destination):
    archive_path = Path(archive_path)
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(destination)
    else:
        with tarfile.open(archive_path) as archive:
            archive.extractall(destination)


def required_libraries(target_platform):
    if target_platform == "linux":
        return ("libEGL.so", "libGLESv2.so")
    if target_platform == "darwin":
        return ("libEGL.dylib", "libGLESv2.dylib")
    if target_platform == "win32":
        return ("libEGL.dll", "libGLESv2.dll", "libEGL.lib", "libGLESv2.lib")
    raise ValueError(f"Unsupported platform: {target_platform}")


def validate_layout(extract_root, target_platform):
    angle_root = Path(extract_root) / "angle"
    if not angle_root.is_dir():
        raise FileNotFoundError("Archive does not contain angle/")

    for header_dir in HEADER_DIRS:
        path = angle_root / "include" / header_dir
        if not path.is_dir():
            raise FileNotFoundError(f"Missing header directory: {path}")

    for name in required_libraries(target_platform):
        path = angle_root / "out" / "Release" / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing library: {path}")

    for name in ("LICENSE", "angle-build.json"):
        path = angle_root / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing metadata file: {path}")

    metadata = load_json(angle_root / "angle-build.json")
    for key in (
        "angleRef",
        "angleCommit",
        "platform",
        "arch",
        "buildType",
        "shared",
        "generatedAt",
        "gnArgs",
    ):
        if key not in metadata:
            raise KeyError(f"angle-build.json is missing {key}")


def check_dependencies(extract_root, target_platform, source_root=None, arch=None):
    out_dir = Path(extract_root) / RELEASE_DIR
    if target_platform == "linux":
        for name in ("libEGL.so", "libGLESv2.so"):
            lib = out_dir / name
            if shutil.which("ldd"):
                output = run_output(["ldd", str(lib)])
            else:
                output = run_output(["readelf", "-d", str(lib)])
            if "not found" in output:
                raise RuntimeError(f"Missing dynamic dependency for {lib}")
    elif target_platform == "darwin":
        for name in ("libEGL.dylib", "libGLESv2.dylib"):
            run(["otool", "-L", str(out_dir / name)])
    elif target_platform == "win32":
        for name in ("libEGL.dll", "libGLESv2.dll"):
            lib = out_dir / name
            imports = read_pe_imports(lib)
            print(f"{name} imports:")
            for imported in imports:
                print(f"  {imported}")
            if not imports:
                raise RuntimeError(f"Could not read dynamic imports from {lib}")


def read_pe_imports(path):
    data = Path(path).read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise RuntimeError(f"Not a PE executable: {path}")

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise RuntimeError(f"Missing PE signature: {path}")

    coff_offset = pe_offset + 4
    section_count = struct.unpack_from("<H", data, coff_offset + 2)[0]
    optional_header_size = struct.unpack_from("<H", data, coff_offset + 16)[0]
    optional_offset = coff_offset + 20
    sections_offset = optional_offset + optional_header_size
    if sections_offset + (section_count * 40) > len(data):
        raise RuntimeError(f"Truncated PE section table: {path}")

    magic = struct.unpack_from("<H", data, optional_offset)[0]
    if magic == 0x10B:
        data_directory_offset = optional_offset + 96
    elif magic == 0x20B:
        data_directory_offset = optional_offset + 112
    else:
        raise RuntimeError(f"Unsupported PE optional header magic 0x{magic:04x}: {path}")

    import_directory_entry = data_directory_offset + 8
    if import_directory_entry + 8 > len(data):
        raise RuntimeError(f"Missing PE import directory: {path}")
    import_rva, import_size = struct.unpack_from("<II", data, import_directory_entry)
    if import_rva == 0 or import_size == 0:
        return []

    sections = []
    for index in range(section_count):
        offset = sections_offset + (index * 40)
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size))

    def rva_to_offset(rva):
        for virtual_address, virtual_size, raw_pointer, raw_size in sections:
            if virtual_address <= rva < virtual_address + virtual_size:
                file_offset = raw_pointer + (rva - virtual_address)
                if file_offset >= raw_pointer + raw_size or file_offset >= len(data):
                    raise RuntimeError(f"PE RVA 0x{rva:x} points outside raw data: {path}")
                return file_offset
        raise RuntimeError(f"Could not map PE RVA 0x{rva:x}: {path}")

    def read_c_string(offset):
        end = data.find(b"\0", offset)
        if end == -1:
            raise RuntimeError(f"Unterminated PE string at 0x{offset:x}: {path}")
        return data[offset:end].decode("ascii", errors="replace")

    imports = []
    descriptor_offset = rva_to_offset(import_rva)
    while True:
        if descriptor_offset + 20 > len(data):
            raise RuntimeError(f"Truncated PE import descriptor: {path}")
        descriptor = struct.unpack_from("<IIIII", data, descriptor_offset)
        if descriptor == (0, 0, 0, 0, 0):
            break
        name_rva = descriptor[3]
        imports.append(read_c_string(rva_to_offset(name_rva)))
        descriptor_offset += 20

    return sorted(set(imports), key=str.lower)


def compile_and_run_smoke(extract_root, target_platform, arch):
    extract_root = Path(extract_root).resolve()
    smoke_cpp = extract_root / "smoke.cpp"
    smoke_cpp.write_text(SMOKE_SOURCE, encoding="utf-8")

    include_dir = extract_root / "angle" / "include"
    lib_dir = extract_root / RELEASE_DIR

    if target_platform == "win32":
        run_windows_smoke(smoke_cpp, include_dir, lib_dir, arch)
        return

    exe = extract_root / "angle-smoke"
    cxx = os.environ.get("CXX", "c++")
    cmd = [
        cxx,
        "-std=c++17",
        "-I",
        str(include_dir),
        str(smoke_cpp),
        "-L",
        str(lib_dir),
        "-lEGL",
        "-lGLESv2",
        "-o",
        str(exe),
    ]
    if target_platform == "linux":
        cmd.insert(-2, "-Wl,-rpath,$ORIGIN/angle/out/Release")
    elif target_platform == "darwin":
        cmd.insert(-2, f"-Wl,-rpath,{lib_dir}")

    run(cmd)

    env = os.environ.copy()
    if target_platform == "linux":
        env["LD_LIBRARY_PATH"] = prepend_env_path(env.get("LD_LIBRARY_PATH"), str(lib_dir))
        if shutil.which("xvfb-run"):
            run(["xvfb-run", "-a", str(exe)], env=env)
        else:
            run([str(exe)], env=env)
    else:
        env["DYLD_LIBRARY_PATH"] = prepend_env_path(env.get("DYLD_LIBRARY_PATH"), str(lib_dir))
        if target_platform == "darwin" and arch in ("x64", "universal"):
            env["ANGLE_SMOKE_ALLOW_NO_DISPLAY"] = "1"
        run([str(exe)], env=env)


def prepend_env_path(current, value):
    if not current:
        return value
    return value + os.pathsep + current


def run_windows_smoke(smoke_cpp, include_dir, lib_dir, arch):
    vcvars = find_vcvarsall()
    normalized_host_arch = windows_host_arch()
    if normalized_host_arch != arch:
        raise RuntimeError(
            f"Windows smoke requires a native {arch} runner, got {normalized_host_arch}"
        )
    vc_arch = arch
    exe = smoke_cpp.parent / "angle-smoke.exe"

    batch = smoke_cpp.parent / "angle-smoke.bat"
    batch_lines = [
        "@echo on",
        f'call "{vcvars}" {vc_arch}',
        "if errorlevel 1 exit /b %errorlevel%",
        (
            f'cl /nologo /EHsc /I "{include_dir}" "{smoke_cpp}" '
            f'/link /LIBPATH:"{lib_dir}" libEGL.lib libGLESv2.lib /OUT:"{exe}"'
        ),
        "if errorlevel 1 exit /b %errorlevel%",
    ]

    batch_lines.extend([
        f'set "PATH={lib_dir};%PATH%"',
        f'"{exe}"',
    ])
    batch.write_text("\r\n".join(batch_lines) + "\r\n", encoding="utf-8")
    run(["cmd", "/d", "/c", str(batch)])


def windows_host_arch():
    for name in ("RUNNER_ARCH", "PROCESSOR_ARCHITEW6432", "PROCESSOR_ARCHITECTURE"):
        value = os.environ.get(name, "").upper()
        if value in ("ARM64", "AARCH64"):
            return "arm64"
        if value in ("X64", "AMD64", "X86_64"):
            return "x64"
    return "unknown"


def find_vcvarsall():
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        raise FileNotFoundError(f"vswhere.exe not found: {vswhere}")
    output = subprocess.check_output(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-property",
            "installationPath",
        ],
        text=True,
    ).strip()
    if not output:
        raise FileNotFoundError("Visual Studio with C++ tools was not found")
    vcvars = Path(output) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvars.exists():
        raise FileNotFoundError(f"vcvarsall.bat not found: {vcvars}")
    return vcvars


def verify_archive(args):
    with tempfile.TemporaryDirectory() as temp:
        extract_archive(args.archive, temp)
        validate_layout(temp, args.platform)
        check_dependencies(temp, args.platform, args.source_root, args.arch)
        if not args.skip_smoke:
            compile_and_run_smoke(temp, args.platform, args.arch)


def smoke_archive(args):
    with tempfile.TemporaryDirectory() as temp:
        extract_archive(args.archive, temp)
        compile_and_run_smoke(temp, args.platform, args.arch)


def list_outputs(args):
    build_dir = Path(args.build_dir)
    for path in sorted(build_dir.iterdir()):
        if path.is_file() and is_interesting_output(path.name):
            size = path.stat().st_size
            print(f"{size:12d} {path.name}")


def is_interesting_output(name):
    suffixes = (
        ".dll",
        ".dylib",
        ".lib",
        ".pdb",
        ".so",
        ".a",
        ".json",
        ".TOC",
    )
    return name.startswith(("libEGL", "libGLESv2", "d3dcompiler")) or name.endswith(suffixes)


def create_universal(args):
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        x64_root = temp / "x64"
        arm64_root = temp / "arm64"
        stage_root = temp / "stage"
        extract_archive(args.x64_archive, x64_root)
        extract_archive(args.arm64_archive, arm64_root)
        shutil.copytree(x64_root / "angle", stage_root / "angle")

        out_dir = stage_root / RELEASE_DIR
        for name in ("libEGL.dylib", "libGLESv2.dylib"):
            run(
                [
                    "lipo",
                    "-create",
                    str(x64_root / RELEASE_DIR / name),
                    str(arm64_root / RELEASE_DIR / name),
                    "-output",
                    str(out_dir / name),
                ]
            )
            run(["lipo", "-info", str(out_dir / name)])

        fix_macos_install_names(out_dir)

        x64_meta = load_json(x64_root / "angle" / "angle-build.json")
        arm64_meta = load_json(arm64_root / "angle" / "angle-build.json")
        metadata = {
            "angleRef": x64_meta.get("angleRef", arm64_meta.get("angleRef")),
            "angleCommit": x64_meta.get("angleCommit", arm64_meta.get("angleCommit")),
            "platform": "darwin",
            "arch": "universal",
            "buildType": "Release",
            "shared": True,
            "generatedAt": datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "gnArgs": {
                "x64": x64_meta.get("gnArgs", {}),
                "arm64": arm64_meta.get("gnArgs", {}),
            },
            "slices": {
                "x64": x64_meta,
                "arm64": arm64_meta,
            },
        }
        (stage_root / "angle" / "angle-build.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        version = archive_version_from_name(args.x64_archive)
        archive_path = artifact_dir / f"angle-{version}-darwin-universal.tar.gz"
        create_tar_gz(stage_root, archive_path)

    print(f"archive={archive_path}")


def archive_version_from_name(path):
    match = re.search(r"angle-(.+?)-darwin-x64\.tar\.gz$", str(path))
    if match:
        return match.group(1)
    return "unknown"


def release_notes(args):
    artifact_root = Path(args.artifact_root)
    archives = sorted(
        path.name
        for path in artifact_root.rglob("*")
        if path.suffix == ".zip" or path.name.endswith(".tar.gz")
    )
    lines = [
        "ANGLE prebuilt shared-library archives.",
        "",
        "Assets:",
    ]
    lines.extend(f"- {name}" for name in archives)
    lines.extend(
        [
            "",
            "Each archive contains angle/include, angle/out/Release, LICENSE, and angle-build.json.",
        ]
    )
    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")


def self_test(args):
    with tempfile.TemporaryDirectory() as temp:
        pe_path = Path(temp) / "minimal-arm64.dll"
        pe_path.write_bytes(create_minimal_pe(import_name="KERNEL32.dll"))
        imports = read_pe_imports(pe_path)
        if imports != ["KERNEL32.dll"]:
            raise AssertionError(f"Unexpected PE imports: {imports!r}")
        print("self-test ok")


def create_minimal_pe(import_name):
    data = bytearray(0x400)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)

    pe_offset = 0x80
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    coff_offset = pe_offset + 4
    optional_offset = coff_offset + 20
    optional_size = 0xF0
    section_offset = optional_offset + optional_size

    struct.pack_into("<HHIIIHH", data, coff_offset, 0xAA64, 1, 0, 0, 0, optional_size, 0x2022)
    struct.pack_into("<H", data, optional_offset, 0x20B)
    data_directory_offset = optional_offset + 112
    struct.pack_into("<II", data, data_directory_offset + 8, 0x200, 40)

    data[section_offset : section_offset + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section_offset + 8, 0x200, 0x200, 0x200, 0x200)

    struct.pack_into("<IIIII", data, 0x200, 0, 0, 0, 0x250, 0)
    data[0x250 : 0x250 + len(import_name) + 1] = import_name.encode("ascii") + b"\0"
    return bytes(data)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    gn = subparsers.add_parser("gn-args")
    gn.add_argument("--platform", choices=sorted(PLATFORM_GN_ARGS), required=True)
    gn.add_argument("--arch", choices=("x64", "arm64"), required=True)
    gn.add_argument("--output", required=True)
    gn.add_argument("--json-output")
    gn.set_defaults(func=write_gn_args)

    package = subparsers.add_parser("package")
    package.add_argument("--source-root", required=True)
    package.add_argument("--build-dir", required=True)
    package.add_argument("--artifact-dir", required=True)
    package.add_argument("--platform", choices=sorted(PLATFORM_GN_ARGS), required=True)
    package.add_argument("--arch", choices=("x64", "arm64"), required=True)
    package.add_argument("--angle-ref", required=True)
    package.add_argument("--angle-commit", required=True)
    package.add_argument("--gn-args-json", required=True)
    package.set_defaults(func=create_package)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--platform", choices=sorted(PLATFORM_GN_ARGS), required=True)
    verify.add_argument("--arch", choices=("x64", "arm64", "universal"), required=True)
    verify.add_argument("--source-root")
    verify.add_argument("--skip-smoke", action="store_true")
    verify.set_defaults(func=verify_archive)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--archive", required=True)
    smoke.add_argument("--platform", choices=sorted(PLATFORM_GN_ARGS), required=True)
    smoke.add_argument("--arch", choices=("x64", "arm64", "universal"), required=True)
    smoke.set_defaults(func=smoke_archive)

    outputs = subparsers.add_parser("list-outputs")
    outputs.add_argument("--build-dir", required=True)
    outputs.set_defaults(func=list_outputs)

    universal = subparsers.add_parser("universal")
    universal.add_argument("--x64-archive", required=True)
    universal.add_argument("--arm64-archive", required=True)
    universal.add_argument("--artifact-dir", required=True)
    universal.set_defaults(func=create_universal)

    notes = subparsers.add_parser("release-notes")
    notes.add_argument("--artifact-root", required=True)
    notes.add_argument("--output", required=True)
    notes.set_defaults(func=release_notes)

    tests = subparsers.add_parser("self-test")
    tests.set_defaults(func=self_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
