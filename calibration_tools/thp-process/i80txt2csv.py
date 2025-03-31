#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import sys
import csv
from datetime import datetime, timedelta, timezone

def convert_log_to_csv(log_file):
    input_file_path = log_file
    output_dir = os.getcwd()

    # Extract the date and time part from the input file name to create the output file name
    log_file_name = os.path.basename(log_file)
    
    # Use regex to replace either '+0300.txt' or '+0200.txt' with an empty string
    base_name = re.sub(r'\+\d{4}\.txt$', '', log_file_name)
    
    # Replace spaces with underscores and create the output file name
    output_file_name = f"i80_{base_name.replace(' ', '_')}.csv"
    output_file_path = os.path.join(output_dir, output_file_name)
    
    with open(input_file_path, 'r') as file:
        lines = file.readlines()

    # Extract UTC offset from the log file
    utc_offset_str = lines[1].split()[-1]  # "(UTC+02:00)"
    utc_offset_str = utc_offset_str[4:-1]  # "+02:00" or "-02:00"
    offset_sign = 1 if utc_offset_str[0] == '+' else -1
    utc_offset_hours, utc_offset_minutes = map(int, utc_offset_str[1:].split(":"))
    
    # Time delta in hours * 60 minutes + minutes in terms of seconds
    total_offset_seconds = offset_sign * (utc_offset_hours * 3600 + utc_offset_minutes * 60)
    total_offset = timedelta(seconds=total_offset_seconds)

    header = ['Datetime', 'Timestamp', 'Time (s)', 'Measurement', 'RH (%RH)', 'Temperature (°C)']

    with open(output_file_path, 'w', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        
        initial_time = None
        for index, line in enumerate(lines[6:]):
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            
            datetime_str = f"{parts[0]} {parts[1]}"
            dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
            dt -= total_offset
            
            timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
            if initial_time is None:
                initial_time = timestamp
            
            time_seconds = timestamp - initial_time
            
            writer.writerow([
                datetime_str,
                timestamp,
                time_seconds,
                index + 1,
                parts[2],
                parts[3]
            ])

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python i80txt2csv.py <log_file>")
        sys.exit(1)

    log_file = sys.argv[1].strip('"')
    convert_log_to_csv(log_file)
