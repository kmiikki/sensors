# Temperature Plateau Detection & Time-Shift Alignment

This Python script automates the calibration of one or two BME280 sensors against a reference temperature sensor. It supports:

1. **Time-Shift Alignment** of the reference sensor (Tref) to account for thermal lag (mass differences).
2. **Temperature Plateau Detection** via linear regressions in sliding windows to find stable intervals (low slopes).
3. **Export** of detailed CSV and TXT files for calibration and visual inspection.

## Features

- **Automatic File Discovery**: Finds the most recent `merged-*.csv` file in the current directory.
- **Configurable Shifts**: Tests integer time shifts for Tref (e.g. `-300` to `+300` seconds) to minimize the std. dev of \(\Delta T = (T_\mathrm{ref, shifted} - T_\mathrm{sensor})\).
- **Plateau Detection**: Uses a sliding window to compute slopes for Tref and each BME280 sensor (`t1`, `t2`), ranking them by \(\sum |slope|\).
- **Threshold & Partitioning**: Filters out intervals whose \(\sum |slope|\) exceeds a threshold, then partitions the remaining intervals to select calibration points.
- **Comprehensive Outputs**: 
  - `talign-thp.csv` – Aligned dataset (with optional time-shift).  
  - `tshift-temp.png` – Plot of shift vs. std. dev.  
  - `tshift-temp-t1.csv` (and `-t2.csv`) – Numeric shift data for each sensor.  
  - `slopes-t1.csv`, `slopes-t2.csv` – Slope data in `analysis-t/` folder.  
  - `t1-ranks.csv`, `t2-ranks.csv`, and TXT equivalents – Final calibration picks.  
  - `temp_plateaus.png` – Visualization of stable plateau intervals, also in `analysis-t/`.

## Requirements

- **Python 3.7+** (or later)
- **NumPy** 
- **Pandas**  
- **matplotlib**  
- **scikit-learn** (for linear regression)

You can install missing packages via:

```bash
pip install numpy pandas matplotlib scikit-learn
```

## Usage

1. **Ensure** you have a `merged-*.csv` in the working directory.  
2. **Run** the script with desired arguments. Example:

```bash
python align_and_plateaus.py \
    -shmin -300 -shmax 300 \
    -i 10 -w 60 -th 0.01 -seg 5
```

### Command-Line Arguments

- **`-shmin`** `<int>` : Minimum time shift to test (default = `-300`).  
- **`-shmax`** `<int>` : Maximum time shift to test (default = `300`).  
  - If you want **no shift**, set `-shmin 0 -shmax 0`.  
- **`-i`** `--interval` `<int>` : Step size (seconds) for sliding window in plateau detection (default = 10).  
- **`-w`** `--window`   `<int>` : Window size (seconds) for plateau detection (default = 60).  
- **`-th`** `--threshold` `<float>` : Maximum sum of absolute slopes (default = 0.01).  
- **`-seg`** `--segments` `<int>` : Number of partition segments to pick final calibration points (default = 5).  

### Example

```bash
# Minimal shift range, effectively no shift
python align_and_plateaus.py -shmin 0 -shmax 0

# Larger shift range, smaller window, etc.
python align_and_plateaus.py -shmin -600 -shmax 600 -i 5 -w 30 -th 0.02 -seg 4
```

## How It Works

1. **Shifting**  
   The script reads the raw data (`Time (s)`, `t1 (°C)`, `t2 (°C)`, `Tref (°C)`), then for each sensor (t1, t2) it tries shifting Tref from `-shmin` to `-shmax` seconds. The shift producing the **lowest std. dev.** of \((T_\mathrm{ref, shifted} - T_\mathrm{sensor})\) is chosen.  

2. **Aligning**  
   A new, aligned DataFrame is created for the overlapping time points, written to `talign-thp.csv`.  

3. **Plateau Detection**  
   The script slides over the aligned data in windows of size `-w` every `-i` seconds. For each window, it calculates slopes for Tref and each sensor, then ranks them by \(\sum |slope|\).  

4. **Threshold & Partition**  
   Intervals exceeding the `-th` threshold are excluded. The remainder is divided into `-seg` partitions (based on mean sensor temperature) to select final calibration points.  

5. **Output**  
   - Detailed slope results in **`analysis-t/slopes-t1.csv`** (and for `t2` if present).  
   - Calibration picks in **`analysis-t/t1-ranks.csv`** / `.txt`.  
   - Plot of time vs. temperature with T-bars indicating calibration points in **`analysis-t/temp_plateaus.png`**.  

## Output Files

1. **`tshift-temp.png`**  
   Plot of shift time vs. std. dev. of \(\Delta T\).  
2. **`tshift-temp-t1.csv`** & **`tshift-temp-t2.csv`**  
   Numeric data for each tested shift (if you have two sensors).  
3. **`talign-thp.csv`**  
   The final time-aligned dataset, with columns:
   ```
   Datetime, Timestamp, Time (s), Measurement, t1 (°C), [t2 (°C)], Tref (°C)
   ```
4. **`analysis-t/slopes-*.csv`**  
   Slope calculations for Tref & each sensor over each time window.  
5. **`analysis-t/t1-ranks.csv`**, **`analysis-t/t1-ranks.txt`** (and likewise for t2)  
   Final sets of calibration points after partitioning.  
6. **`analysis-t/temp_plateaus.png`**  
   Visualization of Tref and sensor(s) with T-bar lines indicating final calibration intervals.

## About the Script

This script is provided as-is, primarily for demonstration and simple calibrations. For more complex scenarios, additional validation or smoothing logic might be necessary.

