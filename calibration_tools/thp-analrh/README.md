# THP Relative Humidity Analyzer (`thp-analrh.py`)

`thp-analrh.py` is a command‑line helper that looks for **plateaus**—periods where the relative‑humidity (RH %) readings of one or two BME280‑based sensors stay effectively flat (slope ≈ 0). When a reference sensor is also in a plateau the script gives precise averages and confidence intervals, making it easy to pull calibration points.

The tool is designed to be run **in the same directory** where `bme280logger-v2.py` (or any other logger that writes a compatible `thp.csv`) is collecting data.

---

## Features

- Works with **one or two RH sensors** automatically.
- Flexible time‑window (`-t`) for the plateau search.
- Generates statistics
  - slope, delta RH %, mean, median, SEM
  - 95 % confidence interval (or exact value when the series is constant)
- Optional plots
  - full‑range & zoomed regression graphs per sensor
  - combined zoomed graph (two sensors)
  - sensor‑to‑sensor difference graph
- Hands‑off monitoring with `watch` or cron.
- Never crashes on flat 0 %/100 % data—constant series are handled gracefully.

---

## Quick start

```bash
# 1. Record RH data (example)
python bme280logger-v2.py &        # writes thp.csv every second

# 2. Analyse the last 10 minutes and generate all output files
python thp-analrh.py -a -t 10
```

The script writes its results to a date‑stamped sub‑directory, e.g.

```
thp-20250419-120233-a20250419-120235/
├── analysis.txt                 # text version of the statistics
├── humidity-full-s1.png         # full‑range graph, sensor 1
├── humidity-range-s1.png        # zoomed graph, sensor 1
├── ...
```

### Live monitoring example

```bash
watch -n 5 "./thp-analrh.py -n -ni -t 2"
```

- refresh every 5 s
- analyse the last 2 minutes
- `-n` means *do not* create files, `-ni` hides the banner—only the stats table updates.

---

## Command‑line options

| Option      | Default           | Purpose                                                    |
| ----------- | ----------------- | ---------------------------------------------------------- |
| `-f <file>` | newest `*thp.csv` | CSV file to analyse                                        |
| `-t <min>`  | `10`              | Length of the time window (minutes) used for the slope fit |
| `-o <rows>` | 3 024 000         | Override maximum rows loaded (memory guard)                |
| `-d <name>` | auto              | Name of the output sub‑directory                           |
| `-n`        | off               | *No files*: print stats only                               |
| `-a`        | off               | **All** outputs (`-l -r -c -diff`, ignoring `-n`)          |
| `-l`        | off               | Full‑range regression graphs                               |
| `-r`        | off               | Zoomed‑range regression graphs                             |
| `-c`        | off               | Combined zoomed graph (two sensors)                        |
| `-diff`     | off               | Difference graph (sensor 2 − sensor 1)                     |
| `-ni`       | off               | Skip the summary banner                                    |
| `-sl`       | off               | Draw the fitted regression line on the full‑range graph    |

---

## Reading the output

A typical stats block looks like this:

```
Statistics
----------
Sensor     : 1
Slope      : -0.0003 %/s
Constant   : 46.08 %
Time (min) : 2
Delta R.H.%: -0.0317
…
R.H.%: 46.061 ± 0.015
R.H.%: [95% CI: 46.046 – 46.077]
```

- **Slope** and **Delta R.H.%** tell you whether the sensor is still drifting.
- When both are ≈ 0 and the CI is narrow, you are on a plateau and can use the **mean ± CI** for calibration.

If the SEM is zero (all readings identical) the script switches to *Constant value* mode and still prints meaningful numbers.

---

## Dependencies

- Python 3.9+
- [`numpy`](https://numpy.org), [`pandas`](https://pandas.pydata.org), [`matplotlib`](https://matplotlib.org), [`scipy`](https://scipy.org)

Install everything at once:

```bash
pip install -r requirements.txt
```

---

## Calibration workflow (example)

1. Keep logging until the reference sensor and DUT(s) all show slope ≈ 0.
2. Run `thp-analrh.py` with a time window fully inside the plateau.
3. Use the printed **Mean ± CI** as your calibration point(s).

---

## License

MIT License – see `LICENSE` for details.

