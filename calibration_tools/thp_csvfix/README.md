# thp_csvfix.py

**Fixes corrupted `thp.csv` files caused by a logfile formatting bug**

---

## Problem

Due to a bug in some versions of `logfile.py`, data log files (`thp.csv`) may be written as a sequence of *individual digits and symbols separated by commas and spaces*, instead of valid CSV rows. This results in files that are unreadable by standard CSV parsers.

**Corrupted example (as found in thp.csv):**

```csv
Datetime, Timestamp, Time (s), Measurement, t1 (°C), RH1% (%), p1 (hPa), t2 (°C), RH2% (%), p2 (hPa)
2, 0, 2, 5, -, 0, 6, -, 0, 8,  , 1, 0, :, 0, 7, :, 3, 0, ., 0, 0, 0, 4, 0, 3, ,,  , 1, 7, 4, 9, 3, 6, 6, 4, 5, 0, ., 0, 0, 0, 4, 0, 3, ,,  , 0, ., 0, ,,  , 1, ,,  , 1, 9, ., 8, 1, ,,  , 1, 2, ., 0, 3, ,,  , 1, 0, 0, 1, ., 7, 9, ,,  , 1, 9, ., 6, 7, ,,  , 1, 3, ., 7, 8, ,,  , 1, 0, 0, 1, ., 7, 9
2, 0, 2, 5, -, 0, 6, -, 0, 8,  , 1, 0, :, 0, 7, :, 3, 1, ., 0, 0, 0, 0, 6, 5, ,,  , 1, 7, 4, 9, 3, 6, 6, 4, 5, 1, ., 0, 0, 0, 0, 6, 5, ,,  , 1, ., 0, ,,  , 2, ,,  , 1, 9, ., 8, 0, ,,  , 1, 2, ., 0, 4, ,,  , 1, 0, 0, 1, ., 7, 5, ,,  , 1, 9, ., 6, 7, ,,  , 1, 3, ., 7, 6, ,,  , 1, 0, 0, 1, ., 8, 1
...
```

*(Each data line is a long sequence of individual characters and numbers, not usable as CSV!)*

---

## Solution

**`thp_csvfix.py`** analyzes the corrupted file, reconstructs each data row, and outputs a proper CSV file.

**Fixed example (thp.fixed.csv):**

```csv
Datetime, Timestamp, Time (s), Measurement, t1 (°C), RH1% (%), p1 (hPa), t2 (°C), RH2% (%), p2 (hPa)
2025-06-09 12:01:12,0.0,1,24.76,38.42,1003.15,25.17,36.41,1003.32
2025-06-09 12:01:13,1.0,2,24.77,38.43,1003.15,25.18,36.39,1003.33
2025-06-09 12:01:14,2.0,3,24.76,38.42,1003.14,25.17,36.39,1003.32
...
```

---

## Usage

* **To fix a file named `thp.csv` in the current directory:**

  ```bash
  ./thp_csvfix.py
  ```

  This creates `thp.fixed.csv`.

* **To fix another file:**

  ```bash
  ./thp_csvfix.py path/to/badfile.csv
  ```

  This creates `badfile.fixed.csv` in the same directory.

---

## Output

* If corrupted lines are detected and fixed:

  ```
  Processed 'thp.csv'. Fixed 40 garbled lines. Wrote output to 'thp.fixed.csv'.
  ```
* If the file is fine:

  ```
  Nothing to fix.
  ```

---

## When to Use

* If your `thp.csv` (or similar) log files contain *broken, comma-separated digits* as above.
* If your logs are fine, or you use a fixed `logfile.py`, you do **not** need this tool.

---

## Requirements

* Python 3.6 or newer

## Author

Kim Miikki, 2025

---

**Note:**
The original file is never overwritten. Output is always written as `<original_name>.fixed.csv`.

