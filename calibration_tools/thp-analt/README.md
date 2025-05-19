# THP Temperature Analyzer (`thp-analt.py`)

`thp-analt.py` is a command-line helper that identifies **plateaus** in temperature measurements—time intervals where the temperature readings of one or two BME280-based sensors stay effectively flat (slope ≈ 0). These stable regions are ideal for calibration. The tool provides regression analysis, confidence intervals, and generates visual output to support temperature sensor calibration.

The script is designed to be run **in the same directory** where `bme280logger-v2.py` (or a similar logger writing a `thp.csv` file) is collecting data.

---

## Features

- Supports **one or two temperature sensors**.
- Customizable regression window via `-t` (in minutes).
- Automatically detects flat (constant) readings and provides exact value statistics.
- Generates:
  - slope, delta °C, mean, median, SEM
  - 95% confidence interval
- Optional plots:
  - full-range regression graphs per sensor
  - zoomed graphs (fitted interval)
  - combined graph for both sensors
  - sensor-to-sensor temperature difference graph
- Tolerant of multiple logging intervals and data gaps.
- CLI interface designed for monitoring and scripting.

---

## Quick Start

```bash
# 1. Start collecting data (example)
python bme280logger-v2.py &       # creates thp.csv with live data

# 2. Analyse the last 10 minutes, generate all plots
python thp-analt.py -a -t 10
```

The analysis results are saved to a timestamped subdirectory, e.g.:

```
thp.csv-a20250520-134530/
├── analysis.txt                     # full statistics
├── temperature-full-s1.png          # full-range graph, sensor 1
├── temperature-range-s1.png         # zoomed plateau, sensor 1
├── temperature-range-(s1,s2).png    # combined zoomed graph
├── temperature-range-diff-(s2-s1).png # sensor 2 minus sensor 1
```

### Live monitoring example

```bash
watch -n 5 "./thp-analt.py -n -ni -t 5"
```

- refresh every 5 seconds
- analyze last 5 minutes
- `-n`: suppress file output, `-ni`: suppress header banner

---

## Command-line options

| Option      | Default             | Purpose                                                        |
| ----------- | ------------------- | -------------------------------------------------------------- |
| `-f <file>` | newest `*thp.csv`   | CSV file to analyze                                            |
| `-t <min>`  | `10`                | Regression window (in minutes)                                 |
| `-o <rows>` | `3 024 000`         | Limit number of rows loaded                                    |
| `-d <name>` | auto                | Output directory name                                          |
| `-n`        | off                 | No file output                                                 |
| `-a`        | off                 | All outputs (`-l -r -c -diff`, overrides other options)        |
| `-l`        | off                 | Full-range regression plots                                    |
| `-r`        | off                 | Zoomed-range regression plots                                  |
| `-c`        | off                 | Combined graph for both sensors                                |
| `-diff`     | off                 | Sensor 2 – Sensor 1 temperature difference                     |
| `-ni`       | off                 | Suppress summary printout                                      |
| `-sl`       | off                 | Overlay regression line on full-range plots                    |

---

## Output Example

Each sensor block in `analysis.txt` includes:

```
Statistics
----------
Sensor     : 1
Slope      : 2e-05 °C/s
Constant   : 63.41 °C
Time (min) : 10
Delta °C   : 0.0118
…
t (°C): 63.606±0.001
t (°C): [95% CI: 63.605–63.607]
```

- **Slope** and **Delta °C** indicate stability.
- If CI is narrow or SEM is zero, the data is stable and usable for calibration.

---

## Dependencies

- Python 3.9+
- [`numpy`](https://numpy.org), [`pandas`](https://pandas.pydata.org), [`matplotlib`](https://matplotlib.org), [`scipy`](https://scipy.org)

Install all requirements with:

```bash
pip install -r requirements.txt
```

---

## Calibration workflow (example)

1. Let your logger collect data until sensors stabilize.
2. Use `thp-analt.py` to analyze a time window inside the plateau.
3. Use the **mean ± CI** as the temperature calibration point.

---

## License

MIT License – see `LICENSE` for details.
