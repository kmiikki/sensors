# Algorithm to Find Calibration Values in t-analysis.py

## Overview

The script `t-analysis.py` identifies optimal calibration points (plateaus) from temperature sensor data. It performs linear regression on selected stable intervals to determine calibration values. Below is the step-by-step algorithm:

---

## Algorithm Steps

### 1. Preparation

* Locate the newest merged CSV file (`merged-YYYYMMDD-hhmmss.csv`) in the current working directory.
* Load the CSV file into a pandas DataFrame.

### 2. Data Validation

* Confirm required columns exist:

  * `Time (s)`
  * `Tref (°C)`
  * `t1 (°C)`
  * Optional: `t2 (°C)`

### 3. Sliding Window Analysis

* Define parameters:

  * Window length (`window`, default=300 rows)
  * Sliding interval (`interval`, default=30 rows)
  * Slope tolerance (`th`, default=0.0005)
  * Maximum allowed temperature difference (`maxdt`, default=5°C)

* Iterate over the data in a sliding window:

  * Calculate mean temperatures and linear regression slopes for the reference and sensors.
  * Identify valid windows where:

    * The absolute difference between sensor and reference means ≤ `maxdt`.
    * Sum of absolute slopes (reference + sensor) ≤ `th`.

### 4. Ranking Plateaus

* Rank windows by the combined slope stability score (lowest score = most stable).
* Store window statistics including indices, means, slopes, and scores.

### 5. Target Calibration Intervals

* Define calibration intervals every 10°C from -50°C to 100°C.
* For each interval, select the best-ranked plateau closest to the target temperature.
* Ensure each calibration point is selected exactly once based on ranking.

### 6. Save Calibration Results

* Save selected plateau ranks and corresponding means to:

  * `{tag}-ranks.csv` (includes ranks)
  * `{tag}-ranks.txt` (excludes ranks)
* Store full analysis data in `{tag}_analysis.csv`.

### 7. Linear Regression Calibration

* Perform linear regression (`scipy.stats.linregress`) using sensor and reference means from selected plateaus:

  * Calculate slope, intercept, R-value, R², standard error, and p-value.
  * Generate scatter plots with regression lines (`{tag}_tref_regression.png`).
  * Save regression summaries to `{tag}_tref_regression.txt`.

### 8. Generate Calibration Plateau Graphs

* Plot full temperature traces with clearly marked calibration intervals.
* Apply automatic scaling of the time-axis (seconds, minutes, hours, days) based on the longest recorded time interval.
* Save plateau overview plots as `{tag}_cal_plateaus.png`.

---

This comprehensive algorithm ensures accurate selection and robust linear regression analysis for temperature sensor calibration.

