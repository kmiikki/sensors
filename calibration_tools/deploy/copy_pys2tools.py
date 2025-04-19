#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Apr 19 20:33:06 2025

@author: Kim

copy_pys2tools.py ‑ Recursively locate every ``*.py`` file beneath the current
working directory and copy each one into ``/opt/tools`` (or a user‑supplied
alternative).  After the copy, the script ensures that **user, group, and other**
all have read and execute permissions (``ugo+rx``).

Typical usage
-------------
$ python copy_pys2tools.py           # copy to /opt/tools (default)
$ python copy_pys2tools.py -d ~/bin  # copy to a custom destination
$ python copy_pys2tools.py -f -q     # force overwrite, stay quiet

Run with *sudo* if your account cannot write to the destination directory.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

__all__ = ["main"]


def _add_ugo_rx(path: Path) -> None:
    """Ensure *ugo+rx* on *path* without clobbering existing permissions."""
    mode = os.stat(path).st_mode
    mode |= (
        stat.S_IRUSR | stat.S_IXUSR |
        stat.S_IRGRP | stat.S_IXGRP |
        stat.S_IROTH | stat.S_IXOTH
    )
    os.chmod(path, mode)


def _copy_py_files(dest: Path, *, force: bool, quiet: bool) -> int:
    """Return the number of files copied."""
    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
        if not quiet:
            print(f"Created destination directory {dest}")

    copied = 0
    cwd = Path.cwd().resolve()
    dest = dest.resolve()

    for src in cwd.rglob("*.py"):
        if src.is_dir():
            # *rglob* should not yield directories, but double‑check.
            continue
        if src.resolve().parent == dest:
            # Skip files already in destination (including this script).
            continue

        target = dest / src.name

        if target.exists() and not force:
            # Skip if destination is newer or same age.
            if target.stat().st_mtime >= src.stat().st_mtime:
                if not quiet:
                    print(f"⇢ Skipping {src} (up‑to‑date)")
                continue

        shutil.copy2(src, target)
        _add_ugo_rx(target)

        if not quiet:
            print(f"✓ Copied {src} → {target}")
        copied += 1

    return copied


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="copy_pys2tools.py",
        description="Copy *.py files to /opt/tools and set ugo+rx permissions.",
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
        total = _copy_py_files(dest_path, force=ns.force, quiet=ns.quiet)
    except PermissionError as exc:
        parser.error(f"Permission denied: {exc}. Try running with elevated privileges.")

    if not ns.quiet:
        print(f"Done. {total} file(s) copied to {dest_path}")


if __name__ == "__main__":
    main()
