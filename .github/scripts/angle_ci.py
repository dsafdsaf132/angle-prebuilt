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
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <cstdio>
#include <cstdlib>

static void fail(const char *message)
{
    std::fprintf(stderr, "%s (EGL error 0x%04x)\n", message, eglGetError());
    std::exit(1);
}

int main()
{
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display == EGL_NO_DISPLAY)
    {
        fail("eglGetDisplay failed");
    }

    EGLint major = 0;
    EGLint minor = 0;
    if (!eglInitialize(display, &major, &minor))
    {
        fail("eglInitialize failed");
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
        gn_args["is_clang"] = False
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
    match = re.search(r"(?:^|/)(\d{4,})(?:$|[-_/])", angle_ref or "")
    if match:
        return match.group(1)

    commit_id = Path(source_root) / "src" / "commit_id.py"
    if commit_id.exists():
        try:
            version = subprocess.check_output(
                [sys.executable, str(commit_id), "position"], cwd=source_root, text=True
            ).strip()
            if version and version != "0":
                return version
        except subprocess.SubprocessError:
            pass

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=source_root, text=True
        ).strip()
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


def check_dependencies(extract_root, target_platform, source_root=None):
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
        tool = find_windows_dependency_tool(source_root)
        for name in ("libEGL.dll", "libGLESv2.dll"):
            lib = out_dir / name
            tool_name, tool_cmd = tool
            if tool_name == "dumpbin":
                run(tool_cmd + ["/DEPENDENTS", str(lib)])
            elif tool_name == "llvm-readobj":
                run(tool_cmd + ["--coff-imports", str(lib)])
            else:
                run(tool_cmd + ["-p", str(lib)])


def find_windows_dependency_tool(source_root):
    dumpbin = shutil.which("dumpbin")
    if dumpbin:
        return "dumpbin", [dumpbin]

    if source_root:
        source_root = Path(source_root)
        llvm_readobj = source_root / "third_party" / "llvm-build" / "Release+Asserts" / "bin" / "llvm-readobj.exe"
        if llvm_readobj.exists():
            return "llvm-readobj", [str(llvm_readobj)]

    for name in ("llvm-readobj", "objdump"):
        path = shutil.which(name)
        if path:
            return name, [path]

    raise FileNotFoundError("Could not find dumpbin, llvm-readobj, or objdump")


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
        run([str(exe)], env=env)


def prepend_env_path(current, value):
    if not current:
        return value
    return value + os.pathsep + current


def run_windows_smoke(smoke_cpp, include_dir, lib_dir, arch):
    vcvars = find_vcvarsall()
    vc_arch = "arm64" if arch == "arm64" else "x64"
    exe = smoke_cpp.parent / "angle-smoke.exe"
    command = (
        f'call "{vcvars}" {vc_arch} && '
        f'cl /nologo /EHsc /I "{include_dir}" "{smoke_cpp}" '
        f'/link /LIBPATH:"{lib_dir}" libEGL.lib libGLESv2.lib /OUT:"{exe}"'
    )
    if arch == "arm64" and os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() != "ARM64":
        run(["cmd", "/s", "/c", command])
        print("Skipping Windows arm64 smoke execution on non-arm64 runner")
        return

    command = (
        command + f' && set "PATH={lib_dir};%PATH%" && "{exe}"'
    )
    run(["cmd", "/s", "/c", command])


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
        check_dependencies(temp, args.platform, args.source_root)
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
    verify.set_defaults(func=verify_archive)

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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
