# Algorithm to Find Calibration Values in rh-analysis.py

## Overview

The script `rh-analysis.py` identifies optimal calibration points (plateaus) from relative humidity (RH) sensor data. It performs linear regression on selected stable intervals to determine calibration values. Below is the step-by-step algorithm:

---

## Algorithm Steps

### 1. Preparation

* Locate the latest merged CSV file (`merged-YYYYMMDD-hhmmss.csv`) from the following directories in order:

  1. `cal/`
  2. `cal/analysis/`
  3. Parent directory
* Read this CSV into a pandas DataFrame.

### 2. Initial Data Filtering

* Filter relevant columns:

  * `Time (s)`
  * `Measurement`
  * `RH1% (%)`, `RH2% (%)`, `RHref (%RH)`

### 3. Sliding Window Analysis

* Define parameters:

  * Window size (`window`, default=180 samples)
  * Interval step (`interval`, default=30 samples)
  * Slope threshold (`th`, default=0.001)
  * Maximum allowed RH difference (`max_rh_diff`, default=10 %RH)

* Perform a sliding window analysis:

  * Calculate linear regression slopes for the reference and each sensor within each window.
  * Identify windows where:

    * The sum of absolute slopes (reference + sensor) is less than the slope threshold.
    * The difference between sensor mean and reference mean is within `max_rh_diff`.
  * Store statistics for each valid window, including mean, min/max, slopes, and indices.

### 4. Rank and Select Calibration Plateaus

* Sort windows based on the `Sum of abs(slope)` ascending (most stable first).
* Rank windows (best plateau = rank 1).

### 5. Determine Calibration Targets

* Compute target intervals for specific RH levels (e.g., 0%, 10%, 20%, etc.).
* Select the best-ranked plateau closest to each target within an acceptable tolerance.
* Each calibration level is selected exactly once based on ranking.

### 6. Save Results

* Write results to CSV and plain text files:

  * `rh1-ranks.csv`, `rh2-ranks.csv` (plateau ranks)
  * Corresponding `.txt` summaries

### 7. Generate Calibration Plots

* Plot selected calibration intervals:

  * Horizontal lines representing sensor mean and reference mean.
  * Vertical lines indicating deviation between sensor and reference values.
* Save plots as:

  * `rh1-cal-levels.png`, `rh2-cal-levels.png`

### 8. Linear Regression for Calibration

* Perform linear regression (`scipy.stats.linregress`) using means from selected calibration plateaus:

  * Calculate slope, intercept, r-value, r², standard error, and p-value.
  * Generate regression summary plots (`rh1%_(%)_regression.png`, `rh2%_(%)_regression.png`).
  * Write regression summaries to `.txt` files and terminal.

### 9. Create Detailed Plateau Graphs

* Generate plots showing RH sensor and reference data with clearly marked calibration intervals.
* Apply automatic time-axis scaling based on the maximum recorded time (seconds, minutes, hours, days).
* Output files:

  * `rh1_cal_plateaus.png`
  * `rh2_cal_plateaus.png`

---

This detailed algorithm ensures precise and repeatable selection of calibration points, providing robust calibration values through linear regression analysis.

