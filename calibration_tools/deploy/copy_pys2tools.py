#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
copy_pys2tools.py — Copy Python utilities (and any additional files explicitly
listed under **[Include]** in *pysdeploy.lst*) into */opt/tools* (or a custom
destination).  All ``*.py`` files are copied **unless** they or their parent
directories are excluded in the **[Exclude]** section of *pysdeploy.lst*.
Directories whose name ends with ``.old`` are always skipped.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path


def _add_ugo_rx(path: Path) -> None:
    """Ensure *ugo+rx* on *path* without clobbering existing permissions."""
    mode = os.stat(path).st_mode
    mode |= (
        stat.S_IRUSR | stat.S_IXUSR |
        stat.S_IRGRP | stat.S_IXGRP |
        stat.S_IROTH | stat.S_IXOTH
    )
    os.chmod(path, mode)


# --------------------------------------------------------------------------- #
# Configuration-file parsing
# --------------------------------------------------------------------------- #
def _read_pysdeploy_list() -> tuple[set[str], set[str], set[str]]:
    """Return (include_files, exclude_dirs, exclude_files) parsed from
    *pysdeploy.lst*.  Lines outside [Include]/[Exclude] are ignored."""
    include_files, exclude_dirs, exclude_files = set(), set(), set()
    
    # Get current path
    cwd = Path.cwd()
    dirs = [cwd, '/opt/tools/']
    for d in dirs:
        lst = Path(os.path.join(d, 'pysdeploy.lst'))
        if lst.is_file():
            break
    if not lst.is_file():
        return include_files, exclude_dirs, exclude_files
    else:
        print(f'Using: {lst}')

    section = None
    for raw in lst.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ll = line.lower()
        if ll == "[exclude]":
            section = "exclude"
            continue
        if ll == "[include]":
            section = "include"
            continue

        if section == "exclude":
            (exclude_dirs if line.endswith("/") else exclude_files).add(
                line.rstrip("/")
            )
        elif section == "include":
            include_files.add(line)

    return include_files, exclude_dirs, exclude_files


def _copy_files(dest: Path, *, force: bool, quiet: bool) -> int:
    """Copy all *.py (except excluded) plus any [Include] files."""
    include_files, exclude_dirs, exclude_files = _read_pysdeploy_list()

    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        if not quiet:
            print(f"Created destination directory {dest}")

    cwd, dest = Path.cwd().resolve(), Path(dest).resolve()
    copied = 0

    for root, dirs, files in os.walk(cwd):
        # prune unwanted dirs *in place* so os.walk never enters them
        dirs[:] = [
            d for d in dirs
            if not d.endswith(".old") and d not in exclude_dirs
        ]
        root_path = Path(root)

        for fname in files:
            rel = Path(root_path, fname).relative_to(cwd)

            # skip explicitly excluded files
            if fname in exclude_files or str(rel) in exclude_files:
                continue

            # decide whether to copy
            if rel.suffix == ".py":
                should_copy = True      # default for .py
            else:
                should_copy = fname in include_files or str(rel) in include_files

            if not should_copy or root_path == dest:
                continue

            src = root_path / fname
            dst = dest / fname
            if dst.exists() and not force and dst.stat().st_mtime >= src.stat().st_mtime:
                if not quiet:
                    print(f"⇢ Skipping {src} (up-to-date)")
                continue

            shutil.copy2(src, dst)
            _add_ugo_rx(dst)
            copied += 1
            if not quiet:
                print(f"✓ Copied {src} → {dst}")

    return copied


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="copy_pys2tools.py",
        description=(
            "Copy all *.py files (except those in [Exclude]) plus any additional "
            "files listed in the [Include] section of pysdeploy.lst to /opt/tools "
            "and set ugo+rx permissions."
        ),
    )
    parser.add_argument(
        "-d", "--dest",
        default="/opt/tools",
        help="Destination directory (default: /opt/tools)",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Overwrite destination files even when they are newer",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress informational output",
    )

    ns = parser.parse_args(argv)
    dest_path = Path(ns.dest).expanduser()

    try:
        total = _copy_files(dest_path, force=ns.force, quiet=ns.quiet)
    except PermissionError as exc:
        parser.error(f"Permission denied: {exc}. Try running with elevated privileges.")

    if not ns.quiet:
        print(f"Done. {total} file(s) copied to {dest_path}")


if __name__ == "__main__":
    main()
