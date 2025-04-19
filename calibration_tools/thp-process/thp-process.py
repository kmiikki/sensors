#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import subprocess
from pathlib import Path
import re


def print_usage():
    print("Usage: thp-process.py [<data_directory>]")
    print("Ensure the required files are present and named correctly.")
    sys.exit(1)


def classify(name):
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', name):
        return "date"
    if re.fullmatch(r'\d{8}-\d{6}', name):
        return "datetime"
    return None


def main():
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help")):
        print_usage()

    if len(sys.argv) == 2:
        data_dir = Path(sys.argv[1])
        if not data_dir.exists():
            print(f"Error: Directory '{data_dir}' does not exist.")
            print_usage()
    else:
        data_dir = Path.cwd()

    # After you parse data_dir …
    kind = classify(data_dir.name)
    if kind in ("date", "datetime"):
        # User pointed at one of the leaf dirs – go up one level
        data_dir = data_dir.parent

    # Find the relevant directories
    DATE_RE      = re.compile(r'^\d{4}-\d{2}-\d{2}$')      # 2025-04-17
    DATETIME_RE  = re.compile(r'^\d{8}-\d{6}$')            # 20250417-092933
    
    datetime_dir, ref_log_dir = None, None
    for subdir in data_dir.iterdir():
        if not subdir.is_dir():
            continue
        name = subdir.name
        if DATE_RE.fullmatch(name):
            ref_log_dir = subdir
        elif DATETIME_RE.fullmatch(name):
            datetime_dir = subdir

    if not datetime_dir or not ref_log_dir:
        print("Error: Required directories not found.")
        print_usage()

    print(f"Found datetime directory: {datetime_dir}")
    print(f"Found reference log directory: {ref_log_dir}")

    # Find the required .txt file
    ref_txt_file = next(ref_log_dir.glob("*.txt"), None)
    thp_csv_file = datetime_dir / "thp.csv"

    if not ref_txt_file:
        print("Error: Reference TXT file not found.")
        print_usage()
    
    if not thp_csv_file.exists():
        print(f"Error: THP CSV file '{thp_csv_file}' not found.")
        print_usage()

    print(f"Reference TXT file: {ref_txt_file}")
    print(f"THP CSV file: {thp_csv_file}")


    # Create 'cal' directory
    cal_dir = data_dir / "cal"
    cal_dir.mkdir(exist_ok=True)
    print(f"Created 'cal' directory: {cal_dir}")

    # Copy the required files to 'cal' directory
    shutil.copy(thp_csv_file, cal_dir)
    shutil.copy(ref_txt_file, cal_dir)
    print(f"Copied required files to 'cal' directory.")

    os.chdir(cal_dir)

    # Generate the correct i80 CSV filename
    i80_base_name = ref_txt_file.stem.replace(' ', '_')
    i80_base_name = i80_base_name[:-5]  # Removing timezone part
    i80_csv_file = f"i80_{i80_base_name}.csv"
    txt2csv_cmd = ["i80txt2csv.py", ref_txt_file.name]
    print(f"Running command: {' '.join(txt2csv_cmd)}")
    subprocess.run(txt2csv_cmd, check=True)
    
    # Combine files with thp-caldata.py
    caldata_cmd = ["thp-caldata.py", "thp.csv", i80_csv_file]
    print(f"Running command: {' '.join(caldata_cmd)}")
    subprocess.run(caldata_cmd, check=True)

    merged_csv_file = f"merged-{datetime_dir.name}.csv"

    # Execute thp-flats.py for calibration values
    if len(sys.argv) == 2:
        flats_cmd = ["thp-flats.py", "-i", "30", "-w", "60", merged_csv_file]
    else:
        flats_cmd = ["thp-flats.py", "-i", "30", "-w", "60", str(cal_dir / merged_csv_file)]
    
    print(f"Running command: {' '.join(flats_cmd)}")
    subprocess.run(flats_cmd, check=True)

    # Verify that the expected output files exist
    analysis_dir = Path("analysis")
    expected_files = [
        analysis_dir / "pressure_analysis.csv",
        analysis_dir / "rh_analysis.csv",
        analysis_dir / "temperature_analysis.csv"
    ]

    missing_files = [str(file) for file in expected_files if not file.exists()]
    if missing_files:
        print("Error: Calibration failed. The following files are missing:")
        print("\n".join(missing_files))
    else:
        print("Calibration process completed successfully.")

if __name__ == "__main__":
    main()

