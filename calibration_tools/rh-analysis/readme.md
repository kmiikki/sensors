# RH Analysis & Calibration Tool

## Overview

`rh-analysis.py` now performs the **entire** pipeline from raw merged THP data to calibrated regression parameters **in one run**. The legacy `rh_analysis.csv` intermediate file and the separate plateau‑selection utility have been removed.

It consumes the most recent **`merged‑YYYYMMDD‑HHMMSS.csv`** file produced by `thp-process.py` and writes all outputs to **`analysis-rh/`**.

### Highlights

* Automatic detection of the latest merged file (no arguments needed).
* Sliding‑window plateau detection, ranking and selection.
* Linear regression for each RH sensor against the reference on the chosen plateaus.
* Publication‑ready plots (300 dpi) and plain‑text summaries.
* Full reproducibility via `analysis-rh/thp-args.log`.

---

## Directory Layout

```text
project/
├── cal/
│   ├── merged-20250430-180233.csv
│   └── analysis/
└── rh-analysis.py
```

The script searches for the newest `merged-*.csv` in:

1. `cal/`
2. `cal/analysis/`
3. the current working directory

---

## Command‑line Options

| Short | Long         | Default | Description                                     |
| ----- | ------------ | ------- | ----------------------------------------------- |
| `-th` | –            | 0.001   | Combined slope threshold for plateau acceptance |
| `-s`  | `--start`    | 0       | First sample index to analyse                   |
| `-w`  | `--window`   | 180     | Sliding‑window length (samples)                 |
| `-i`  | `--interval` | 30      | Step between windows (samples)                  |
| –     | `--maxdiff`  | 10      | Max allowed \|RHsensor – RHref\| (%%RH)         |
| `-a`  | `--auto`     | False   | Auto‑scale X‑axis units on plateau plots        |

All parameters—**including defaults**—are echoed to `analysis-rh/thp-args.log`; overridden values are marked with `*`, enabling deterministic reruns.

---

## Typical Usage

Run from the project root (auto‑picks latest merged file):

```bash
python3 rh-analysis.py
```

Or customise the analysis window and plotting:

```bash
python3 rh-analysis.py -th 0.002 -w 240 -a
```

---

## Outputs

| Path                                | Purpose                                   |
| ----------------------------------- | ----------------------------------------- |
| `analysis-rh/thp-args.log`          | Date, input file path, full argument list |
| `analysis-rh/rh1-ranks.csv/.png`    | Ranked plateau list & visualisation (RH1) |
| `analysis-rh/rh2-ranks.csv/.png`    | Same for RH2 (if present)                 |
| `analysis-rh/rh1%_(%)_regression.*` | Regression plot & stats for RH1           |
| `analysis-rh/rh2%_(%)_regression.*` | Regression plot & stats for RH2           |
| `analysis-rh/*_cal_plateaus.png`    | Timeline plot with selected plateaus      |

---

## Expected Columns in *merged‑*.csv\*

```text
Time (s),Measurement,RH1% (%),RH2% (%),RHref (%RH)
```

Extra columns are ignored.

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
