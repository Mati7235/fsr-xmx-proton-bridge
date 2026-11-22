#!/usr/bin/env python3
"""Assemble the downloadable folders under build/release.

Each folder is self-contained: the scripts from game/ or driver/ plus a copy of
the fsr-xmx command with its libraries and profiles under fsr-xmx/. No DLLs,
no OptiScaler files and no upstream checkout are copied; a player supplies
those, and a stray one in the source folder is skipped.
"""
import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE_ROOT = REPO / "build" / "release"
TOOL_DIR = REPO / "installer"
TOOL_FILES = (
    "fsr-xmx",
    "lib/common.sh",
    "lib/ini_edit.py",
    "lib/vdf.py",
)
PAYLOAD_SUFFIXES = {".dll", ".ini", ".zip", ".7z"}
SKIP_DIRS = {"__pycache__", ".git"}
SYSTEM_DIRS = ("/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64",
               "/mnt", "/opt", "/proc", "/root", "/run", "/sbin", "/srv",
               "/sys", "/usr", "/var")


def fail(message):
    print(f"build_release: {message}", file=sys.stderr)
    raise SystemExit(1)


def is_ancestor(candidate, path):
    return candidate == path or candidate in path.parents


def release_root(argument):
    if argument is None:
        return RELEASE_ROOT
    root = Path(argument).expanduser().resolve()
    home = Path.home().resolve()
    if root == Path(root.anchor):
        fail("refusing to use the filesystem root as the output folder")
    if root == home:
        fail("refusing to use the home folder as the output folder")
    if is_ancestor(root, home):
        fail(f"refusing to use {root}, because it holds the home folder")
    if is_ancestor(root, REPO):
        fail(f"refusing to use {root}, because it is the repository or holds it")
    for system in SYSTEM_DIRS:
        system_path = Path(system)
        if root == system_path:
            fail(f"refusing to use {root}, because it is a system folder")
        if system_path in root.parents:
            fail(f"refusing to use {root}, because it is inside {system_path}")
    return root


def copy_sources(source, target, skipped):
    count = 0
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if SKIP_DIRS.intersection(rel.parts):
            continue
        if path.is_dir():
            (target / rel).mkdir(parents=True, exist_ok=True)
            continue
        if path.suffix.lower() in PAYLOAD_SUFFIXES:
            skipped.append(rel.as_posix())
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        count += 1
    return count


def copy_tool(target):
    tool_target = target / "fsr-xmx"
    count = 0
    for rel in TOOL_FILES:
        source = TOOL_DIR / rel
        if not source.is_file():
            fail(f"{source} is missing")
        destination = tool_target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        count += 1
    profiles = sorted((TOOL_DIR / "profiles").glob("*.conf"))
    if not profiles:
        fail(f"no profile in {TOOL_DIR / 'profiles'}")
    for source in profiles:
        destination = tool_target / "profiles" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        count += 1
    return count


def clean(target, root):
    if target.parent != root or target == root:
        fail(f"refusing to clean {target}, which is not one folder inside {root}")
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)


def assemble(root, name, source):
    if not source.is_dir():
        fail(f"{source} is missing")
    target = root / name
    clean(target, root)
    target.mkdir(parents=True)
    skipped = []
    count = copy_sources(source, target, skipped)
    count += copy_tool(target)
    print(f"{target} ({count} files)")
    if skipped:
        print(f"  skipped third-party files: {', '.join(skipped)}")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the download folders under build/release.")
    parser.add_argument("--out", metavar="FOLDER",
                        help="release root other than build/release; the two "
                             "folders are created inside it")
    args = parser.parse_args()

    root = release_root(args.out)
    if root.exists() and not root.is_dir():
        fail(f"{root} is not a folder")
    root.mkdir(parents=True, exist_ok=True)

    total = 0
    for name, source in (("fsr-xmx-game", REPO / "game"),
                         ("fsr-xmx-driver", REPO / "driver")):
        total += assemble(root, name, source)
    print(f"2 folders, {total} files, each with its own fsr-xmx and no third-party binaries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
