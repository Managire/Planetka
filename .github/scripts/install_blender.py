#!/usr/bin/env python3
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def _major_minor(version):
    parts = version.split(".")
    if len(parts) < 2:
        raise ValueError(f"Invalid Blender version: {version}")
    return parts[0], parts[1]


def _candidate_filenames(version, system_name, machine):
    machine = (machine or "").lower()
    if system_name == "Linux":
        return [f"blender-{version}-linux-x64.tar.xz"]
    if system_name == "Windows":
        return [f"blender-{version}-windows-x64.zip"]
    if system_name == "Darwin":
        arch = "arm64" if "arm" in machine or "aarch" in machine else "x64"
        alt_arch = "x64" if arch == "arm64" else "arm64"
        return [
            f"blender-{version}-macos-{arch}.dmg",
            f"blender-{version}-macos-{arch}.zip",
            f"blender-{version}-macos-{alt_arch}.dmg",
            f"blender-{version}-macos-{alt_arch}.zip",
        ]
    raise RuntimeError(f"Unsupported OS: {system_name}")


def _download_with_fallback(version, system_name, machine, temp_dir):
    major, minor = _major_minor(version)
    base = f"https://download.blender.org/release/Blender{major}.{minor}"
    errors = []
    for filename in _candidate_filenames(version, system_name, machine):
        url = f"{base}/{filename}"
        target = Path(temp_dir) / filename
        try:
            print(f"[install_blender] Downloading {url}")
            urllib.request.urlretrieve(url, target)
            return target
        except urllib.error.HTTPError as exc:
            errors.append(f"{url} -> HTTP {exc.code}")
        except urllib.error.URLError as exc:
            errors.append(f"{url} -> URL error: {exc.reason}")
    raise RuntimeError(
        "Failed to download Blender build. Tried:\n" + "\n".join(errors)
    )


def _extract_linux_tar(archive_path, install_dir):
    with tarfile.open(archive_path, "r:xz") as tar:
        tar.extractall(install_dir)


def _extract_windows_zip(archive_path, install_dir):
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(install_dir)


def _extract_macos_dmg(archive_path, install_dir):
    attach = subprocess.run(
        ["hdiutil", "attach", str(archive_path), "-nobrowse", "-readonly"],
        check=True,
        capture_output=True,
        text=True,
    )
    mount_point = None
    for line in attach.stdout.splitlines():
        for token in line.split():
            if token.startswith("/Volumes/"):
                mount_point = token
    if not mount_point:
        raise RuntimeError("Could not determine mount point for DMG.")

    mount_path = Path(mount_point)
    app_candidates = list(mount_path.glob("*.app"))
    if not app_candidates:
        subprocess.run(["hdiutil", "detach", str(mount_path), "-quiet"], check=False)
        raise RuntimeError(f"No .app bundle found in mounted DMG: {mount_path}")

    app_src = app_candidates[0]
    app_dst = Path(install_dir) / app_src.name
    if app_dst.exists():
        shutil.rmtree(app_dst)
    shutil.copytree(app_src, app_dst, symlinks=True)
    subprocess.run(["hdiutil", "detach", str(mount_path), "-quiet"], check=False)


def _extract_macos_zip(archive_path, install_dir):
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(install_dir)


def _find_blender_binary(install_dir):
    install_dir = Path(install_dir)
    candidates = []
    if os.name == "nt":
        for path in install_dir.rglob("blender.exe"):
            if path.is_file():
                candidates.append(path)
    else:
        for path in install_dir.rglob("blender"):
            if path.is_file() and os.access(path, os.X_OK):
                candidates.append(path)
        for path in install_dir.rglob("Blender.app/Contents/MacOS/Blender"):
            if path.is_file() and os.access(path, os.X_OK):
                candidates.append(path)

    if not candidates:
        raise RuntimeError(f"No Blender binary found under {install_dir}")

    candidates.sort(key=lambda p: len(str(p)))
    return candidates[0]


def _write_output(path, value):
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(str(value), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Install Blender for CI runs.")
    parser.add_argument("--version", required=True, help="Blender version, e.g. 5.0.1")
    parser.add_argument("--install-dir", required=True, help="Install destination directory")
    parser.add_argument("--output-file", default="", help="Optional file to write Blender binary path")
    args = parser.parse_args()

    system_name = platform.system()
    machine = platform.machine()
    install_dir = Path(args.install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="planetka_blender_dl_") as temp_dir:
        archive = _download_with_fallback(args.version, system_name, machine, temp_dir)

        if archive.suffixes[-2:] == [".tar", ".xz"]:
            _extract_linux_tar(archive, install_dir)
        elif archive.suffix.lower() == ".zip":
            if system_name == "Darwin":
                _extract_macos_zip(archive, install_dir)
            else:
                _extract_windows_zip(archive, install_dir)
        elif archive.suffix.lower() == ".dmg":
            _extract_macos_dmg(archive, install_dir)
        else:
            raise RuntimeError(f"Unsupported archive type: {archive.name}")

    blender_bin = _find_blender_binary(install_dir)
    print(f"[install_blender] Blender binary: {blender_bin}")
    _write_output(args.output_file, blender_bin)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[install_blender] ERROR: {exc}", file=sys.stderr)
        raise

