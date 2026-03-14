from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, TextIO


@dataclass(frozen=True)
class CSVRotateConfig:
    prefix: str
    dirpath: Path
    headers: list[str]
    flush_every: int = 1


class CSVRotatingWriter:
    def __init__(self, cfg: CSVRotateConfig) -> None:
        if cfg.flush_every < 1:
            raise ValueError("flush_every must be >= 1")

        self.cfg = cfg
        self._fh: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self._rows_since_flush = 0
        self._current_path: Path | None = None

    def __enter__(self) -> "CSVRotatingWriter":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def path(self) -> Path | None:
        return self._current_path

    def _target_path(self) -> Path:
        self.cfg.dirpath.mkdir(parents=True, exist_ok=True)
        return self.cfg.dirpath / f"{self.cfg.prefix}.csv"

    def _ensure_open(self) -> None:
        if self._fh is not None and self._writer is not None:
            return

        path = self._target_path()
        is_new_file = not path.exists()

        self._fh = path.open("a", newline="", encoding="utf-8", buffering=1)
        self._writer = csv.DictWriter(
            self._fh,
            fieldnames=self.cfg.headers,
            extrasaction="ignore",
        )
        self._current_path = path

        if is_new_file:
            self._writer.writeheader()
            self._flush()

    def _flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()
        self._rows_since_flush = 0

    def write(self, row: Mapping[str, object]) -> None:
        self._ensure_open()
        assert self._writer is not None

        out_row = {key: row.get(key, "") for key in self.cfg.headers}
        self._writer.writerow(out_row)
        self._rows_since_flush += 1

        if self._rows_since_flush >= self.cfg.flush_every:
            self._flush()

    def writerows(self, rows: Iterable[Mapping[str, object]]) -> None:
        for row in rows:
            self.write(row)

    def close(self) -> None:
        if self._fh is not None:
            self._flush()
            self._fh.close()

        self._fh = None
        self._writer = None
        self._current_path = None