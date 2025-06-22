# Algorithm – Temperature Time‑Shift & Plateau Calibration (`thp-t-flats.py`)

---

## 1. Purpose

`thp-t-flats.py` calibrates one or two **BME280** temperature channels (`t1`, `t2`) against a high‑precision reference thermometer. Because the reference probe has substantially more thermal mass than the lightweight BME280 sensor, it responds **more slowly** to ambient changes. The script therefore compensates this lag by shifting the reference trace **backward** (usually a negative shift) in time so that both curves describe the same physical moment. It then detects **temperature plateaus**—periods of thermal equilibrium—via sliding‑window slope analysis, performs linear regression on plateau means, and stores the resulting coefficients in a persistent calibration dictionary (`thpcal.json`).

## 2. Core Features

| Feature                         | Description                                                                                                                  |       |                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ----- | --------------------- |
| **Time‑shift optimisation**     | Searches integer shifts (`‑shmin` → `‑shmax`, 1 s step) to minimise the standard deviation of ΔT = `Tref_shifted − Tsensor`. |       |                       |
| **Automatic plateau detection** | Sliding windows (`‑i` step, `‑w` width) compute slopes; intervals with low Σ                                                 | slope | indicate equilibrium. |
| **Segmented sampling**          | Remaining plateaus are partitioned into `‑seg` equal‑temperature bands to cover the full range.                              |       |                       |
| **Visual analytics**            | Generates `tshift-temp.png` (shift curve) and `temp_plateaus.png` (detected plateaus).                                       |       |                       |
| **Comprehensive exports**       | Writes aligned dataset, slope tables, plateau picks, regression plots & txt, plus JSON calibration.                          |       |                       |
| **Dual‑sensor aware**           | Independently optimises shift and regression for `t1` and `t2`.                                                              |       |                       |
| **Zone/number mapping**         | Optional `‑cal` flag stores results under zone & sensor codes (e.g. `C3,4`).                                                 |       |                       |

## 3. Expected CSV Structure

```
Time (s), Measurement, t1 (°C), t2 (°C), Tref (°C), Datetime
```

`t2 (°C)` is optional; additional columns are ignored.

## 4. Command‑Line Interface

| Flag                 | Arg   | Meaning                                  | Default |                   |          |
| -------------------- | ----- | ---------------------------------------- | ------- | ----------------- | -------- |
| `‑shmin`             | INT   | Minimum shift to test (s)                | ‑300    |                   |          |
| `‑shmax`             | INT   | Maximum shift to test (s)                | 300     |                   |          |
| `‑i`, `‑‑interval`   | INT   | Step between window starts (s)           | 10      |                   |          |
| `‑w`, `‑‑window`     | INT   | Window length (s)                        | 60      |                   |          |
| `‑th`, `‑‑threshold` | FLOAT | Max Σ                                    | slope   | to accept plateau | 5 × 10⁻⁴ |
| `‑seg`, `‑‑segments` | INT   | Number of temperature bands to sample    | 5       |                   |          |
| `‑cal`               | SPEC  | Zone,num1[,num2] mapping (e.g. `C3,4`)   | —       |                   |          |
| `‑z`                 | —     | Zero out time component in JSON datetime | —       |                   |          |

## 5. Processing Pipeline

1. **Locate dataset** – newest `merged‑*.csv` in cwd.
2. **Shift search** – for each sensor, compute std(ΔT) across the shift range; choose best shift.
3. **Write optimisation curve** – CSV + `tshift-temp.png`.
4. **Build aligned dataset** – interpolate `Tref` at shifted times; save `talign-thp.csv`.
5. **Sliding‑window slopes** – compute slopes for `Tref` & sensor(s); rank by Σ|slope|.
6. **Export slopes** – `slopes-t1.csv` (+ `t2`).
7. **Select plateaus** – filter by `‑th`, partition into `‑seg` bins, keep first per bin.
8. **Save picks** – `t1-ranks.csv/txt` etc.
9. **Visualise plateaus** – `temp_plateaus.png` with T‑bars.
10. **Linear regression** – fit `y = ax + b` on plateau means; save plot + txt.
11. **Update ** – merge calibration under zone/number and `"T"` key.

## 6. Output Artefacts

| File                                | Contents                    | Notes                      |
| ----------------------------------- | --------------------------- | -------------------------- |
| `analysis-t/tshift-temp.png`        | Shift vs std plot           | plus CSV(s)                |
| `analysis-t/talign-thp.csv`         | Time‑aligned dataset        |                            |
| `analysis-t/slopes-t1.csv`          | Window slopes & ranks       | `slopes-t2.csv` if present |
| `analysis-t/t1-ranks.csv` / `.txt`  | Final plateau means         | ditto `t2`                 |
| `analysis-t/temp_plateaus.png`      | Traces with plateau markers |                            |
| `analysis-t/t1_tref_regression.png` | Plateau regression          | ditto `t2`                 |
| `analysis-t/t1_tref_regression.txt` | Coefficients & R²           | ditto `t2`                 |
| `thpcal.json`                       | Persistent calibration dict | always updated             |

## 7. Example Session

```console
$ python thp-t-flats.py -shmin -600 -shmax 600 -i 5 -w 30 -th 0.0005 -seg 6 -cal C3,4
[t1] best shift = -123 s, std = 0.014902
[t2] best shift = -115 s, std = 0.015377
Regression on chosen plateaus …
  t1 → slope=0.99912  intercept=-0.0136  R²=0.998512  N=30
  t2 → slope=0.99885  intercept=-0.0152  R²=0.998033  N=30
Calibration dictionary updated → ./thpcal.json
Done – results saved in analysis-t
```

## 8. Extending or Customising

- **Higher‑order fits** – replace `linregress` with polynomial regression if non‑linearity appears.
- **Adaptive windows** – tune `interval`, `window`, `threshold` for faster or more conservative plateau selection.
- **Instrument‑specific lag** – widen shift range for probes with large thermal mass.
- **Batch runs** – wrap in cron / GitHub Actions to recalibrate automatically.

## 9. Dependencies

- Python ≥ 3.9
- `numpy`, `pandas`, `matplotlib`, `scikit‑learn`, `scipy`
- Local library `thpcaldb`


