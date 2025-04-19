#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convert ISO‑8859‑1 encoded .txt and .csv files in the **current directory** to
UTF‑8 and save them into a sub‑directory called ``utf-8``.

While converting, the script also fixes a naming mistake in the *header line*
that occasionally appends a percent sign ("%") to pressure sensor names.  Only
these two very specific occurrences are corrected:

* ``p1%`` → ``p1``
* ``p2%`` → ``p2``

No other percent signs in the file are touched.  The rest of the UTF‑8
conversion logic is unchanged.

Created on Mon Mar 17 12:44:57 2025
Author : Kim (modified by ChatGPT on Apr 19 2025)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List


def get_file_encoding(file_path: str | os.PathLike) -> str | None:
    """Return the charset reported by the *file* command (in lower‑case).

    If no charset is reported, *None* is returned.
    """
    result = subprocess.run(
        ["file", "-bi", str(file_path)], capture_output=True, text=True, check=False
    )
    mime_type = result.stdout.strip()
    charset_prefix = "charset="
    if charset_prefix in mime_type:
        return mime_type.split(charset_prefix)[-1].lower()
    return None


def _fix_pressure_header(line: str) -> str:
    """Remove the stray '%' in *p1%* and *p2%* (nothing else)."""
    return line.replace("p1%", "p1").replace("p2%", "p2")


def convert_to_utf8(file_path: str | os.PathLike, output_dir: str | os.PathLike) -> None:
    """Convert *file_path* from ISO‑8859‑1 to UTF‑8 and write it to *output_dir*.

    The first (header) line is passed through :func:`_fix_pressure_header` before
    being written so that any ``p1%`` / ``p2%`` typos are corrected.
    """
    with open(file_path, "r", encoding="iso-8859-1", newline="") as file:
        lines: List[str] = file.readlines()

    if lines:
        lines[0] = _fix_pressure_header(lines[0])

    output_path = Path(output_dir) / Path(file_path).name
    with open(output_path, "w", encoding="utf-8", newline="") as file:
        file.writelines(lines)


def main() -> None:
    utf8_dir = Path("utf-8")
    current_dir = Path.cwd()

    # Gather *.txt and *.csv files in the current directory (non‑recursive).
    files = [f for f in current_dir.iterdir() if f.suffix in {".txt", ".csv"}]

    directory_created = False
    for file in files:
        encoding = get_file_encoding(file)
        if encoding == "iso-8859-1":
            if not directory_created:
                utf8_dir.mkdir(exist_ok=True)
                directory_created = True
            convert_to_utf8(file, utf8_dir)
            print(f"Converted {file.name} → {utf8_dir / file.name}")


if __name__ == "__main__":
    main()
