# rh-linreg: Linear Regression for Humidity Sensor Calibration

This Python script performs a linear calibration analysis of BME280 relative humidity sensors against a factory-calibrated Vaisala reference sensor. It reads a merged CSV file, applies optional time range filtering, fits a linear regression model for each active sensor, and outputs regression parameters, R² statistics, and optional diagnostic plots.

## Features

- Automatically locates the latest merged CSV file (`merged-YYYYMMDD-HHMMSS.csv`)
- Supports two BME280 humidity sensors: `RH1% (%)` and `RH2% (%)`
- Filters data based on valid humidity range (0.01–99.99% RH)
- Optional time range clipping using command-line arguments
- Reports:
  - Regression formula `y = ax + b`
  - R² (coefficient of determination)
  - MSE (mean squared error)
  - Training/test set sizes
- Saves results to `.txt` and `.png` files unless disabled

## Requirements

- Python 3.x
- `numpy`
- `pandas`
- `scikit-learn`
- `matplotlib`

Install dependencies with:

```bash
pip install numpy pandas scikit-learn matplotlib
````

## Usage

```bash
python rh-linreg.py [options]
```

### Options

* `-i FILE`, `--input FILE`
  Path to a `merged-*.csv` file. If omitted, the script auto-detects the newest file from `./cal/`, `./cal/analysis/`, or the current directory.

* `-s SEC`, `--start SEC`
  Clip analysis to start from this time in seconds (optional).

* `-e SEC`, `--end SEC`
  Clip analysis to end at this time in seconds (optional).

* `-n`
  Disable graph generation.

* `-N`
  Disable both graph generation and regression summary file outputs.

## Output

For each active sensor (`RH1%`, `RH2%`), the script will generate:

* `<sensor>_rhref_regression.txt`: Regression summary including formula, R², MSE
* `<sensor>_rhref_regression.png`: Scatter plot with regression line (unless `-n` or `-N` is used)

## Example

```bash
python rh-linreg.py -s 300 -e 1800
```

This runs the regression on the most recent merged file using data from 300 s to 1800 s.

## Author

Kim Miikki, 2025
