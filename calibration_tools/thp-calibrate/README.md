# THP Calibration Utility (`thp-calibrate.py`)

`thp-calibrate.py` retro‑fits **calibrated** temperature, relative‑humidity and/or pressure values to an **existing** data log that was recorded with [`bme280logger‑v2.py`](./bme280logger-v2.py) *without* on‑the‑fly calibration. It reads the raw CSV, fetches the latest calibration parameters from your `calibration.db`, appends calibrated columns that follow the live‑logger naming conventions, and writes both a new CSV and a concise log report.

---

## Why would I need this?

- You logged a long experiment without calibration enabled and now want to correct the values.
- You added or updated calibration lines in the database *after* logging.
- You need calibrated data for plotting/analysis but prefer to keep the raw log untouched.

---

## Features

- **CSV → DataFrame → CSV** pipeline powered by *pandas*.
- Automatically detects and tolerates header variations (missing `%`, extra spaces, etc.).
- Applies `y = slope · x + const` using parameters stored in `calibration.db` (`calibration_dates` + `calibration_line`).
- Adds calibrated columns with the same style the live logger would have written (e.g. `Tcal1 (°C)`, `RHcal2% (%)`).
- Clamps calibrated relative‑humidity to the physically valid range 0 – 100 %.
- Writes a compact **`thp-cal.log`** describing which calibrations were applied (slope, constant, `cal_id`).

---

## Prerequisites

| requirement | tested version |
|-------------|----------------|
| Python | ≥ 3.9 |
| `pandas` | ≥ 1.5 |
| [`thpcaldb.py`](./thpcaldb.py) **and** a compatible `calibration.db` in the *same directory* | |

Install Python dependency:

```bash
pip install pandas
```

---

## Usage

The script is executable (`chmod +x thp-calibrate.py`) or can be invoked with `python thp-calibrate.py`.

```bash
# basic – uses thp.csv in the current directory
./thp-calibrate.py

# custom input / output paths
./thp-calibrate.py -i data/raw_thp.csv -o results/thp-cal.csv

# apply RH calibration for sensors C11 and C12
./thp-calibrate.py -cal C11,12
```

### Command‑line options

| option | default | explanation |
|--------|---------|-------------|
| `-i`, `--input` *FILE* | `thp.csv` | raw CSV to read |
| `-o`, `--output` *FILE* | `thp-cal.csv` | calibrated CSV to write |
| `-cal` *zone,num1[,num2]* | *(none)* | identical to live logger: specify zone letters and one or two sensor numbers to calibrate |

> **Tip:** If you ran the live logger *with* `-cal`, you do **not** need this script – the data are already calibrated.

---

## What you get

```
./thp-cal.csv   # original columns + Tcal1 (°C), RHcal1% (%), …
./thp-cal.log   # plain‑text calibration summary
```

### Column naming convention

| raw logger column | calibrated column |
|-------------------|-------------------|
| `t1 (°C)` | `Tcal1 (°C)` |
| `RH1% (%)` | `RHcal1% (%)` |
| `p1 (hPa)` | `Pcal1 (hPa)` |
| *same pattern for sensor 2…* | |

Calibrated columns are appended **after** all original columns so any existing scripts that consumed the raw file keep working.

### `thp-cal.log` sample

```
=== THP CSV Calibration Report ===

Source CSV : thp.csv
Generated  : 2025-04-20 14:30:12

--- Calibration Data ---
Sensor 1 (Zone C, Number 11) – Relative Humidity:
   slope    = 0.9834
   constant = 2.115
   cal_id   = 47

Sensor 2 (Zone C, Number 12) – Relative Humidity:
   slope    = 0.9791
   constant = 3.008
   cal_id   = 48

--- Summary ---
Output CSV : thp-cal.csv
RH values are clamped to 0‑100 %.
=== End of Report ===
```

---

## Implementation notes

- The regex helper gracefully handles column headers such as `RH1`, `RH1%`, `RH1% (%)`.
- Each calibration record returned by `thpcaldb.Calibration` corresponds to **one** measurement type (`label` field). The script maps that label → raw header → calibrated column.
- The calibration database is expected in the same directory as the script; adjust the path in the source if your layout differs.

---

## Limitations / TODO

- Only two sensors are supported (matching the live logger design).
- No automatic graph generation – that remains in the live logger.
- Pressure and temperature calibrations run only if matching rows exist in the DB.

---

## License

MIT © 2024‑2025 Kim Miikki
