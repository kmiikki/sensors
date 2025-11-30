#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logfile.py — simple reusable writers for dataloggers

Classes
-------
DataLog:
    CSV-like logger for measurement data. Supports optional time-stamped
    subdirectory, header handling, and configurable separator (csv_sep).
    The *first line* written is treated as the header; if it's a list, each
    field is written as-is; if it's a string, it is normalized by split/strip/join
    to remove stray spaces around delimiters.

ErrorLog:
    Human-readable error log (CSV-formatted). Defaults to csv_sep=", " for
    on-screen readability, but is configurable.

Notes
-----
- No sensor-specific logic here.
- Backward-friendly API; new parameters are optional with defaults.

Author: Kim Miikki (original) + small cleanups
License: MIT
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Union


class DataLog:
    """Data log object class (CSV-like)."""
    _dt_list: list[str] = []

    # Constructor
    def __init__(
        self,
        timestamp: int,
        file_path: str = "",
        name: str = "",
        ext: str = "log",
        subdirs: bool = True,
        ts_prefix: bool = False,
        csv_sep: str = ",",
    ) -> None:
        """
        Parameters
        ----------
        timestamp : int
            Epoch seconds used for time-stamped naming.
        file_path : str
            Base folder for outputs ("" = current working directory).
        name : str
            Base filename without extension.
        ext : str
            File extension (default "log"; set "csv" if you prefer).
        subdirs : bool
            If True, create a time-stamped subdirectory (YYYYmmdd-HHMMSS).
        ts_prefix : bool
            If True, prepend the timestamp to the *filename* as well.
        csv_sep : str
            CSV separator to use when joining fields (default ",").
        """
        self._csv_sep = csv_sep
        self._ts_prefix = ts_prefix
        self._is_header = False

        # Generate unique timestamp part
        dt = datetime.fromtimestamp(timestamp)
        self._dt_part = dt.strftime("%Y%m%d-%H%M%S")
        if self._dt_part in DataLog._dt_list:
            raise ValueError(
                f"The given datetime ({self._dt_part}) is already in use. "
                "Unable to create a new log object."
            )
        DataLog._dt_list.append(self._dt_part)

        # Build directory path
        base = file_path
        if base != "" and not base.endswith("/"):
            base += "/"
        if subdirs:
            base += self._dt_part + "/"
        if (len(base) > 0) and (not os.path.exists(base)):
            os.makedirs(base)

        # Create file path
        self.log_name = ""
        if ts_prefix:
            self.log_name += self._dt_part + "-"
        self.log_name += name + "." + ext
        self.full_path = os.path.abspath(base + self.log_name)
        self._dir_path = os.path.abspath(base) if base else os.path.abspath(".")
        if not self._dir_path.endswith("/"):
            self._dir_path += "/"

        # Create an empty file
        open(self.full_path, "w").close()

    def _normalize_header_line(self, s: str) -> str:
        """
        Normalize a header string: split -> strip -> join using self._csv_sep.
        This removes any accidental spaces around delimiters in the header.
        """
        parts = [p.strip() for p in s.split(self._csv_sep)]
        return self._csv_sep.join(parts)

    def write(self, data: Union[list, str]) -> None:
        """
        Write a line to the log.

        - If `data` is a list:
            * If this is the first line (header), strip() each field and join.
            * Otherwise, join as-is using csv_sep.
        - If `data` is a string:
            * If this is the first line (header), normalize by split/strip/join.
            * Otherwise, write as-is.
        """
        if isinstance(data, list):
            if not self._is_header:
                # Header list: strip each field once
                line = self._csv_sep.join([str(x).strip() for x in data])
                self._is_header = True
            else:
                # Data row from list: join as-is with the configured separator
                line = self._csv_sep.join(map(str, data))
        else:
            line = str(data)
            if not self._is_header:
                # Header string: normalize to remove stray spaces around separators
                try:
                    line = self._normalize_header_line(line)
                except Exception:
                    # If anything goes wrong, write the raw header string
                    pass
                self._is_header = True

        with open(self.full_path, "a", encoding="utf-8", newline="") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")

    @property
    def dir_path(self) -> str:
        """Absolute directory path (always ends with '/')."""
        return self._dir_path

    @property
    def dt_part(self) -> str:
        """Time-stamp fragment 'YYYYmmdd-HHMMSS' used for this log instance."""
        return self._dt_part

    @property
    def ts_prefix(self) -> bool:
        """Whether the timestamp is also prefixed to the filename."""
        return self._ts_prefix

    # Destructor
    def __del__(self) -> None:
        if self._dt_part in DataLog._dt_list:
            DataLog._dt_list.remove(self._dt_part)


class ErrorLog:
    """Error log object class (human-readable CSV by default)."""
    _log_list: list[str] = []

    # Constructor
    def __init__(
        self,
        dir_path: str = "",
        name: str = "error",
        ext: str = "log",
        dt_part: str = "",
        ts_prefix: bool = False,
        csv_sep: str = ", ",
    ) -> None:
        """
        Parameters
        ----------
        dir_path : str
            Target folder ("" = current working directory). Safe with empty path.
        name : str
            Base filename without extension.
        ext : str
            File extension.
        dt_part : str
            Optional timestamp fragment to include in the filename if ts_prefix=True.
        ts_prefix : bool
            If True and dt_part is provided, prepend it to the filename.
        csv_sep : str
            Field separator used in the error log (default ', ' for readability).
        """
        self._csv_sep = csv_sep

        # Build full path safely (no indexing on empty strings)
        base = dir_path or ""
        if base and not base.endswith("/"):
            base += "/"

        name_parts = []
        if ts_prefix and dt_part:
            name_parts.append(dt_part)
        name_parts.append(name)
        filename = "-".join(name_parts) + f".{ext}"
        full_path = (base + filename) if base else filename

        # Duplicate check
        if full_path in ErrorLog._log_list:
            raise ValueError(
                f"The error log object ({full_path}) already exists. "
                "Unable to create a new error log object."
            )

        # Create file
        try:
            open(full_path, "w").close()
        except Exception:
            print("Unable to create an error log")
            return

        ErrorLog._log_list.append(full_path)
        self._full_path = full_path
        self._is_header = False

    def write(self, timestamp: int, measurement: int, error_text: str) -> None:
        """
        Append one error event as a CSV line:
        'Datetime{sep}Measurement{sep}Event'
        """
        with open(self._full_path, "a", encoding="utf-8", newline="") as f:
            if not self._is_header:
                f.write(self._csv_sep.join(["Datetime", "Measurement", "Event"]) + "\n")
                self._is_header = True

            dt_text = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S.%f")
            out = self._csv_sep.join([dt_text, str(measurement), error_text])
            f.write(out + "\n")

    # Destructor
    def __del__(self) -> None:
        if hasattr(self, "_full_path") and (self._full_path in ErrorLog._log_list):
            ErrorLog._log_list.remove(self._full_path)


if __name__ == "__main__":
    ...
