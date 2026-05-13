# Four-sensor DPS8000 example run

This directory contains one real four-sensor DPSlogger v2.4 measurement run.

The example is intended for:

- checking the DPSlogger v2.4 output file layout
- testing `dps-plot` without connected hardware
- demonstrating the difference between per-sensor detail CSV files and the researcher-friendly summary CSV
- showing the generated plot, histogram, regression, and statistics outputs

## Files

Configuration and metadata:

- `dps_config.json`: generated bus/sensor configuration
- `dps_run_20260511-163435.json`: run metadata for the measurement session

Measurement CSV files:

- `dps_addr01_20260511-163435.csv`: per-sensor detail CSV for address 01
- `dps_addr02_20260511-163435.csv`: per-sensor detail CSV for address 02
- `dps_addr03_20260511-163435.csv`: per-sensor detail CSV for address 03
- `dps_addr04_20260511-163435.csv`: per-sensor detail CSV for address 04
- `dps_summary_20260511-163435.csv`: researcher-friendly summary CSV with logical sensor columns `p1`, `p2`, `p3`, and `p4`

Generated plots:

- `dps_summary_plot_20260511-163435.png`: combined p1..p4 summary plot
- `dps_addrNN_plot_20260511-163435.png`: per-sensor pressure-vs-time plots
- `dps_addrNN_20260511-163435_hist.png`: per-sensor histogram diagnostics
- `dps_addrNN_20260511-163435_regression.png`: per-sensor regression diagnostics
- `dps_addrNN_20260511-163435_stats.txt`: per-sensor statistics and CI95 output

## Recreate plots

From this directory:

```bash
dps-plot --dir . --session 20260511-163435 --all
````

Black-and-white output:

```bash
dps-plot --dir . --session 20260511-163435 --all --bw
```

Plot only the combined summary figure:

```bash
dps-plot dps_summary_20260511-163435.csv --combined
```

Plot one detail CSV:

```bash
dps-plot dps_addr04_20260511-163435.csv
```

## Notes

The detail CSV files are address-based and use names such as `dps_addr01_...csv`.

The summary CSV is logical-id based and uses columns such as `p1`, `p2`, `p3`, and `p4`.

The histogram and regression files are diagnostic outputs. The main researcher-facing plots are the per-sensor pressure-vs-time plots and the combined summary plot.


