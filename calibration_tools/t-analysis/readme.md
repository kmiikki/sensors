# Temperature Analysis & Calibration Tool (`t-analysis.py`)

## Overview

`t-analysis.py` performs the **entire** pipeline from raw merged THP data to calibrated temperature‑regression parameters **in one run**. The legacy intermediate CSVs and the separate plateau‑selection helper are no longer needed.

It consumes the most recent **`merged‑YYYYMMDD‑HHMMSS.csv`** produced by `thp-process.py` and writes its outputs to:

* the *same directory* as the merged file — full window listings `t1_analysis.csv`, `t2_analysis.csv`
* an analysis directory **`analysis-t/`** — plots, chosen plateau summaries, regressions, and run logs

### Highlights

* Automatic detection of the latest merged file (no arguments needed).
* Sliding‑window plateau detection, ranking and selection for **T1** and **T2** sensors.
* Linear regression of each sensor temperature against `Tref (°C)` on the chosen plateaus.
* Publication‑ready plots (300 dpi) and detailed plain‑text regression summaries.
* Full reproducibility via `analysis-t/thp-args.log`.

---

## Directory Layout

```text
project/
├── cal/
│   ├── merged-20250430-180233.csv
│   └── analysis/
└── t-analysis.py
```

`t-analysis.py` searches for the newest `merged-*.csv` in:

1. `cal/`
2. `cal/analysis/`
3. the current working directory

---

## Command‑line Options

| Short | Long         | Default | Description                                       |
| ----- | ------------ | ------- | ------------------------------------------------- |
| `-th` | –            | 5e‑4    | Combined slope threshold for plateau acceptance   |
| `-s`  | `--start`    | 0       | First sample index to analyse                     |
| `-w`  | `--window`   | 300     | Sliding‑window length (samples)                   |
| `-i`  | `--interval` | 30      | Step between windows (samples)                    |
| –     | `--maxdt`    | 2.0     | Max allowed \|Tsensor – Tref\| (°C) inside window |
| `-a`  | `--auto`     | False   | Auto‑scale X‑axis units on plateau plots          |

All parameters—including defaults—are echoed to `analysis-t/thp-args.log`; overridden values are marked with `*`, ensuring deterministic reruns.

---

## Typical Usage

Run from the project root (auto‑picks latest merged file):

```bash
python3 t-analysis.py
```

Customise the analysis window and plotting:

```bash
python3 t-analysis.py -th 2e-4 -w 600 -i 60
```

---

## Outputs

| Path                                              | Purpose                                   |
| ------------------------------------------------- | ----------------------------------------- |
| `<merge dir>/t1_analysis.csv` / `t2_analysis.csv` | Full candidate plateau list (all windows) |
| `analysis-t/thp-args.log`                         | Date, input file path, full argument list |
| `analysis-t/t1-ranks.csv/.txt`                    | Chosen plateau means & Rank (T1)          |
| `analysis-t/t2-ranks.csv/.txt`                    | Same for T2 (if present)                  |
| `analysis-t/t1_tref_regression.*`                 | Regression plot & stats for T1            |
| `analysis-t/t2_tref_regression.*`                 | Regression plot & stats for T2            |
| `analysis-t/*_cal_plateaus.png`                   | Timeline plot with selected plateaus      |

---

## Expected Columns in *merged‑\*.csv*

```text
Time (s),Measurement,t1 (°C),t2 (°C),Tref (°C)
```

Extra columns (RH, pressure, etc.) are ignored.

---

## Dependency Stack

* Python ≥ 3.9
* numpy, pandas, matplotlib
* scipy, scikit‑learn

Install everything with:

```bash
pip install -r requirements.txt
```

---

## License

MIT — see `LICENSE` for details.
