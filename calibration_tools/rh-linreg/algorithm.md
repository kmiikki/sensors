# Algorithm – Relative Humidity Linear Regression Calibration (`rh-linreg.py`)

---

## 1. Purpose

`rh-linreg.py` automates the linear calibration of one or two **BME280** humidity sensors (`RH1%`, `RH2%`) against a laboratory reference sensor recorded as **RHref (%RH)**.  The script discovers the latest merged data file, fits a linear model (`y = ax + b`) for each active sensor with a reproducible 70 / 30 train‑test split, evaluates goodness of fit, produces human‑ and machine‑readable artefacts, and keeps a consolidated calibration dictionary (`thpcal.json`).

## 2. Core Features

| Feature                      | Description                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------- |
| **Automatic file discovery** | Finds the most recent `merged-YYYYMMDD-hhmmss.csv` in `cal/`, `cal/analysis/`, or project root. |
| **Flexible clipping**        | Optional `-s / -e` arguments further restrict the time range without widening defaults.         |
| **Dual‑sensor support**      | Independently processes `RH1%` and `RH2%` when present.                                         |
| **Robust regression**        | Uses scikit‑learn’s `LinearRegression`, 70 / 30 split, `random_state=42`.                       |
| **Quality metrics**          | Reports slope, intercept, MSE, and R².                                                          |
| **Optional graphics**        | Saves a scatter + fit PNG per sensor (suppressed with `-n` or `-N`).                            |
| **Persistent calibration**   | Merges results into `thpcal.json`, keyed by *zone* & *sensor number* via `-cal`.                |
| **Audit trail**              | Text summary per sensor (`rh1_rhref_regression.txt`, etc.) with timestamp & input filename.     |

## 3. Expected CSV Structure (minimum)

```
Time (s), Measurement, RH1% (%), RH2% (%), RHref (%RH), Datetime
```

The script keeps only these columns; additional columns are ignored.

## 4. Command‑Line Interface

| Flag            | Arg              | Meaning                                                    | Default       |
| --------------- | ---------------- | ---------------------------------------------------------- | ------------- |
| `-i`, `--input` | FILE             | Explicit CSV path                                          | *auto‑detect* |
| `-s`, `--start` | SEC              | Clip start time (s)                                        | 0             |
| `-e`, `--end`   | SEC              | Clip end time (s)                                          | *file end*    |
| `-n`            | —                | Skip graph generation                                      | —             |
| `-N`            | —                | Skip graphs **and** txt/json outputs                       | —             |
| `-cal`          | ZONE,NUM1[,NUM2] | Map sensor(s) to calibration zone & number (e.g. `C11,12`) | —             |
| `-z`            | —                | Zero‑out time component in the logged datetime             | —             |

## 5. Processing Pipeline

1. **Locate dataset** – via `find_latest_merged_csv()` if `-i` absent.
2. **Load & filter** – `read_and_filter_data()` keeps only relevant columns.
3. **Determine valid range** – clips to `[start,end]`; enforces sensor‑specific limits (*0.01 … 99.99 %RH*).
4. **Train/test split** – 70 % train, 30 % test, shuffle with fixed seed.
5. **Fit model** – `LinearRegression().fit(X_train, y_train)` per sensor.
6. **Evaluate** – compute *MSE* and *R²* on hold‑out test set.
7. **Report** – `report_regression()` prints and (unless `-N`) writes `*.txt`.
8. **Plot** – `plot_calib()` saves `*.png` unless `-n`/`-N`.
9. **Persist calibration** – merge results into `thpcal.json` (create if missing).

## 6. Output Artefacts

| File                                                    | When emitted                    | Contents                      |
| ------------------------------------------------------- | ------------------------------- | ----------------------------- |
| `rh1_rhref_regression.txt` / `rh2_rhref_regression.txt` | default; skipped with `-N`      | Fit coefficients & metrics    |
| `rh1_rhref_regression.png` / `rh2_rhref_regression.png` | default; skipped with `-n`/`-N` | Scatter plot + fitted line    |
| `thpcal.json`                                           | default; skipped with `-N`      | Nested calibration dictionary |

### `thpcal.json` Schema (excerpt)

```json
{
  "12": {
    "C12": {
      "H": {
        "datetime": "2025-04-07 00:00:00",
        "label": "Relative humidity",
        "name": "RH1%",
        "slope": 0.9987,
        "constant": -0.6123,
        "r2": 0.9876
      }
    }
  }
}
```

Keys:

- **Outer** – sensor number (stringified int)
- **Second** – zone + sensor (e.g. `C12`)
- **Third** – measurement type (`H` = humidity)

## 7. Example Session

```console
$ python rh-linreg.py -cal C11,12 -s 300 -e 1200
rh-linreg analysis - Kim Miikki 2025
Analysis time : 2025-06-22 14:58:01
Input file    : cal/merged-20250622-144045.csv
Sensor        : 11
Formula       : y = 0.9987x - 0.6123
Intercept     : -0.6123
Coefficient   : 0.9987
N (training)  : 532
N (test)      : 228
Test MSE      : 0.1432
Test R²       : 0.9889
→ saved plot to rh1_rhref_regression.png
→ saved stats to rh1_rhref_regression.txt
→ saved thpcal.json
```

## 8. Extending or Customising

- **Different split ratios** – adjust `train_test_split()` in `run_regression()`.
- **Alternative models** – swap `LinearRegression` for any scikit‑learn regressor.
- **Multi‑sensor calibration** – add more sensor entries to the `sensors` list.
- **CI/CD** – schedule the script in GitHub Actions to update calibration on push.

## 9. Dependencies

- Python ≥ 3.9
- `numpy`, `pandas`, `matplotlib`, `scikit‑learn`
- Local library `thpcaldb` providing `parse_zone_numbers()`

Install via

```bash
pip install -r requirements.txt
```


