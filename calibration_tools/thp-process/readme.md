# THP Process Automation Tool

This repository contains a set of Python scripts for automating the data processing workflow for THP (Temperature, Humidity, Pressure) analysis. The main script, `thp-process.py`, orchestrates the execution of several independent scripts that convert, merge, calibrate, and analyze data files. It is designed to work with a specific file and directory structure as described below.

---

## Description

The THP Process Automation Tool streamlines the processing of data by automatically:

- **Detecting** the required directories and files.
- **Converting** a reference log file (TXT) to CSV format using `i80txt2csv.py`.
- **Merging** the THP CSV data with the converted log data via `thp-caldata.py`.
- **Calibrating** the merged data using `thp-flats.py`.
- **Producing** a set of analysis files and graphs in a newly created `cal` directory.

### Mandatory File Structure

Your working directory must contain two specific directories with matching dates:

```
.
├── 2025-01-27
│   └── 2025-01-27 13.24.25+0200.txt
└── 20250127-132440
    └── thp.csv
```

- The **reference log directory** is named using the `YYYY-MM-DD` format and must contain a TXT file named in the format:  
  `YYYY-MM-DD HH.MM.SS+OFFSET.txt`
- The **data directory** uses the `YYYYMMDD-HHMMSS` format and must contain the `thp.csv` file.
- **Important:** The date indicated in both directories must match exactly.

---

## Installation

Follow these steps to install the scripts on your system:

1. **Copy Scripts to the Tools Directory**

   Copy all Python files (`*.py`) to the `/opt/tools` directory:
   ```bash
   cp *.py /opt/tools
   ```

2. **Ensure the Program Directory is in the PATH**

   Check your current PATH:
   ```bash
   printenv PATH
   ```
   
   To permanently add `/opt/tools` to your PATH, create a script under `/etc/profile.d/`:
   ```bash
   sudo nano /etc/profile.d/tools.sh
   ```
   Add the following line:
   ```bash
   export PATH="$PATH:/opt/tools"
   ```
   Save and close the file.

3. **Set Execution Permissions**

   Grant execute permissions to all the Python scripts:
   ```bash
   sudo chmod ugo+rx /opt/tools/*.py
   ```

4. **(Optional) Create `/opt/tools` Directory if It Does Not Exist**

   If the directory is missing, create it:
   ```bash
   sudo mkdir /opt/tools
   cp *.py /opt/tools
   sudo chmod ugo+rx /opt/tools/*.py
   sudo nano /etc/profile.d/tools.sh
   ```
   Ensure the file includes:
   ```bash
   export PATH="$PATH:/opt/tools"
   ```
   Then reboot your system to apply the changes:
   ```bash
   sudo reboot
   ```

---

## Usage

1. **Prepare the Directory Structure**

   Make sure your working directory is set up as follows:
   ```
   .
   ├── 2025-01-27
   │   └── 2025-01-27 13.24.25+0200.txt
   └── 20250127-132440
       └── thp.csv
   ```
   The dates in the directory names and file names must match.

2. **Run the Main Script**

   Navigate to your working directory (e.g., `/home/.../demo`) and execute:
   ```bash
   cd /home/.../demo
   thp-process.py
   ```
   
   **Example Output:**
   ```
   Found datetime directory: /home/.../demo/20250127-132440
   Found reference log directory: /home/.../demo/2025-01-27
   Reference TXT file: /home/.../demo/2025-01-27/2025-01-27 13.24.25+0200.txt
   THP CSV file: /home/.../demo/20250127-132440/thp.csv
   Created 'cal' directory: /home/.../demo/cal
   Copied required files to 'cal' directory.
   Running command: i80txt2csv.py 2025-01-27 13.24.25+0200.txt
   Running command: thp-caldata.py thp.csv i80_2025-01-27_13.24.25.csv
   Result saved to merged-20250127-132440.csv
   Running command: thp-flats.py -i 30 -w 60 /home/.../demo/cal/merged-20250127-132440.csv
   Calibration process completed successfully.
   ```

3. **Resulting Files**

   After running `thp-process.py`, your directory structure will include a new `cal` directory with the following contents:
   ```
   .
   ├── 2025-01-27
   │   └── 2025-01-27 13.24.25+0200.txt
   ├── 20250127-132440
   │   └── thp.csv
   └── cal
       ├── 2025-01-27 13.24.25+0200.txt
       ├── analysis
       │   ├── combined_pressure_slopes_by_rank.png
       │   ├── combined_pressure_slopes_by_time.png
       │   ├── combined_rh_slopes_by_rank.png
       │   ├── combined_rh_slopes_by_time.png
       │   ├── combined_temp_slopes_by_rank.png
       │   ├── combined_temp_slopes_by_time.png
       │   ├── combined_thp_by_time.png
       │   ├── pressure_analysis.csv
       │   ├── rh_analysis.csv
       │   └── temperature_analysis.csv
       ├── i80_2025-01-27_13.24.25.csv
       ├── merged-20250127-132440.csv
       └── thp.csv
   ```

   **Important Files for Post Analysis:**
   - `merged-20250127-132440.csv` → Use with `thp-t-flats.py` for Temperature Plateau Detection & Time-Shift Alignment.
   - `rh_analysis.csv` → Use with `rh-analysis.py` for Relative Humidity Plateau Detection.

---

## Script Overview

### thp-process.py
- **Purpose:** Automates the entire data processing workflow.
- **Main Features:**
  - Validates the required file structure and matching dates.
  - Creates a working directory (`cal`) for processing.
  - Executes the subsequent scripts in sequence.
- **Usage:** Run `thp-process.py` in a directory with the mandatory files.

### i80txt2csv.py
- **Purpose:** Converts the reference TXT log file into a CSV format.
- **Usage:**  
  ```bash
  i80txt2csv.py <date> <filename>
  ```

### thp-caldata.py
- **Purpose:** Merges the THP CSV data with the CSV output from `i80txt2csv.py`.
- **Usage:**  
  ```bash
  thp-caldata.py <thp_csv_file> <i80_csv_file>
  ```

### thp-flats.py
- **Purpose:** Performs the calibration process on the merged data.
- **Main Features:**
  - Processes data with configurable interval and window parameters.
  - Outputs analysis graphs and CSV files.
- **Usage:**  
  ```bash
  thp-flats.py -i <interval> -w <window> <merged_csv_file>
  ```

### Post-Processing Scripts

- **thp-t-flats.py**
  - **Purpose:** Detects temperature plateaus and aligns time-shifts.
  - **Usage:** Run this script separately using the merged CSV file.
  
- **rh-analysis.py**
  - **Purpose:** Detects relative humidity plateaus.
  - **Usage:** Run this script separately using the `rh_analysis.csv` file.

---

## Notes

- **Directory & Filename Consistency:** Ensure that the date formats in the directory names and filenames match exactly.
- **PATH Configuration:** The `thp-process.py` script and its dependent scripts must be in a directory included in your PATH (e.g., `/opt/tools`).
- **Independent Scripts:** All scripts (except `thp-process.py`) can be executed independently if needed.
