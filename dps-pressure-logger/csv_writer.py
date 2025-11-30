#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Mapping
import csv
import datetime as dt
import io
import os


@dataclass
class CSVRotateConfig:
    """
    Configuration for CSVRotatingWriter.
    """
    prefix: str = "samples"
    dirpath: Path = Path.cwd()
    headers: Sequence[str] = ()
    flush_every: int = 50
    encoding: str = "utf-8"
    newline: str = ""


class CSVRotatingWriter:
    """
    Daily-rotating CSV writer.

    - Files named '{prefix}_YYYYMMDD.csv' under `dirpath`.
    - Rotates when local date changes.
    - Writes header once per file.
    - Flushes every `flush_every` rows and on rotate/close.
    """

    def __init__(self, cfg: CSVRotateConfig):
        if not cfg.headers:
            raise ValueError("CSVRotatingWriter requires fixed 'headers' column order.")
        if cfg.flush_every < 1:
            raise ValueError("flush_every must be >= 1")

        self.cfg = cfg
        self._date: Optional[dt.date] = None
        self._fh: Optional[io.TextIOWrapper] = None
        self._writer: Optional[csv.DictWriter] = None
        self._rows_written_since_flush: int = 0

        self.cfg.dirpath.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> "CSVRotatingWriter":
        self._open_for_today()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def current_path(self) -> Optional[Path]:
        if self._date is None:
            return None
        return self._make_path_for_date(self._date)

    def write(self, row: Mapping[str, object]) -> None:
        self._maybe_rotate()
        assert self._writer is not None
        filtered = {h: row.get(h, "") for h in self.cfg.headers}
        self._writer.writerow(filtered)
        self._rows_written_since_flush += 1
        if self._rows_written_since_flush >= self.cfg.flush_every:
            self._flush()

    def writerow(self, row: Mapping[str, object]) -> None:
        self.write(row)

    def writerows(self, rows: Iterable[Mapping[str, object]]) -> None:
        for r in rows:
            self.write(r)

    def close(self) -> None:
        try:
            self._flush()
        finally:
            if self._fh:
                try:
                    self._fh.close()
                finally:
                    self._fh = None
                    self._writer = None
                    self._date = None

    def _local_today(self) -> dt.date:
        return dt.datetime.now(dt.timezone.utc).astimezone().date()

    def _make_path_for_date(self, d: dt.date) -> Path:
        name = f"{self.cfg.prefix}_{d.strftime('%Y%m%d')}.csv"
        return (self.cfg.dirpath / name).resolve()

    def _open_for_today(self) -> None:
        today = self._local_today()
        if self._date == today and self._fh and not self._fh.closed:
            return

        if self._fh:
            self._flush()
            self._fh.close()

        self._date = today
        path = self._make_path_for_date(today)

        new_file = not path.exists() or path.stat().st_size == 0
        self._fh = open(path, "a", encoding=self.cfg.encoding,
                        newline=self.cfg.newline, buffering=1)
        self._writer = csv.DictWriter(self._fh, fieldnames=list(self.cfg.headers),
                                      extrasaction="ignore")

        if new_file:
            self._writer.writeheader()
            self._fh.flush()
        self._rows_written_since_flush = 0

    def _maybe_rotate(self) -> None:
        if self._date != self._local_today():
            self._open_for_today()

    def _flush(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.flush()
        self._rows_written_since_flush = 0
