#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 25 18:52:02 2024

@author: Kim
"""

import re
import sqlite3
from datetime import datetime

class Calibration:
    """
    A class that retrieves the latest calibration data (slope, const) from
    the calibration_dates and calibration_line tables for the specified
    (zone, num) and stores a calibration dictionary for keys:
      'Temperature', 'Relative Humidity', and 'Pressure'.
    If no valid calibration is found, the constructor returns None.
    """
    
    def __new__(cls, db_path: str, zone: str, num: int):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Retrieve all calibration rows for the given sensor.
            # We also fetch the calibration_date so we can pick the latest per label.
            query = """
            SELECT cd.cal_id, cd.label, cl.slope, cl.const, cd.calibration_date
            FROM calibration_dates cd
            JOIN calibration_line cl ON cd.cal_id = cl.cal_id
            WHERE cd.zone = ?
              AND cd.num = ?
            ORDER BY cd.label, cd.calibration_date DESC
            """
            cursor.execute(query, (zone, num))
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return None
            
            # Build a dictionary with keys for each calibration type.
            # Since rows are ordered by label and calibration_date descending,
            # the first row for each label is the most recent.
            cal_data = {}
            seen_labels = set()
            for row in rows:
                cal_id, label, slope, const, cal_date = row
                if label not in seen_labels:
                    cal_data[label] = {"slope": slope, "const": const, "cal_id": cal_id}
                    seen_labels.add(label)
            
            instance = super().__new__(cls)
            instance._cal_data = cal_data
            return instance
        
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return None

    def __init__(self, db_path: str, zone: str, num: int):
        # Additional initialization can be done here if needed.
        pass

    def get_calibrated_value(self, sensor_value: float, calibration_type: str) -> float:
        """
        Returns the calibrated value for a given raw sensor value
        based on the calibration type.
        For 'Relative Humidity', the result is clamped between 0 and 100.
        """
        data = self._cal_data.get(calibration_type)
        if data is None:
            raise ValueError(f"No calibration data found for type '{calibration_type}'")
        
        calibrated = data["slope"] * sensor_value + data["const"]
        if calibration_type == "Relative Humidity":
            calibrated = max(0, min(calibrated, 100))
        return calibrated



def parse_zone_numbers(cal_str: str):
    """
    Parses a calibration string of the form:
       zone[,number1][,number2]
    and returns a tuple of zone, int1, int2 or None, according
    to the rules below.

    
    Update: instead of combos return zone, int1, int2 or None, according
    to the rules below.

    Examples:
      "-cal B2,3"   => "B2", "B3"
      "-cal C11,12" => "C11", "C12"
      "-cal C11"    => "C11", None
      "-cal A,,10"  => None, "A10"

    The 'zone' may already include digits (e.g. "B2"), in which case
    that implies zone="B" and number1=2. Or 'zone' may be just letters
    (e.g. "A"), in which case number1 is None unless it appears after
    the comma(s).
    """

    # Trim surrounding whitespace just in case
    cal_str = cal_str.strip()

    # Regex to capture up to three comma-separated parts:
    #   group(1) = first chunk (could be "B2", "C11", "A", etc.)
    #   group(2) = second chunk (could be "3", "", "12", etc.)
    #   group(3) = third chunk (could be "10", etc.)
    pattern = r'^([^,]+)(?:,([^,]*))?(?:,([^,]*))?$'
    match = re.match(pattern, cal_str)
    if not match:
        # If it doesn't match at all, return two Nones
        return (None, None)

    first_chunk  = match.group(1)  # e.g. "B2", "C11", or "A"
    second_chunk = match.group(2)  # e.g. "3", "", "12", or None
    third_chunk  = match.group(3)  # e.g. "10", or None

    # A small helper to see if a string is purely digits
    def is_digits(s: str) -> bool:
        return bool(s) and s.isdigit()

    # Another helper to separate a leading alpha zone from trailing digits
    # e.g. "B2" -> ("B", 2), "C11" -> ("C", 11), "A" -> ("A", None)
    def split_zone_digits(segment: str):
        # Try to match:  one or more letters, followed by zero or more digits
        m = re.match(r'^([A-Za-z]+)(\d*)$', segment)
        if m:
            z = m.group(1)
            num_part = m.group(2)
            if num_part == '':
                return z, None
            else:
                return z, int(num_part)
        else:
            # If it's all digits (rare case) or doesn't match at all, return (None, None)
            # But for your examples, typically if there's no letters, we treat it as no zone
            if is_digits(segment):
                return (None, int(segment))
            return (segment, None)  # Fallback; might or might not be meaningful

    # 1) Parse the first chunk to figure out the "base zone" and possibly a first number
    base_zone, first_num = split_zone_digits(first_chunk)

    # 2) Decide how to form the *first combination*:
    #
    #    - If first_num is not None, that means the user typed something like "B2"
    #      so the first combination is "B2" (base_zone + first_num).
    #    - Otherwise, if first_num is None, we check second_chunk for digits
    #      to form the first combination.
    #
    #    - If there's no number at all, the first combination is None.

    num1 = None
    num2 = None
    
    if first_num is None:    
        # Cases:
        # A    -> zone=A, first_num=None, second_chunk None, third_chunk None
        # A,,  -> zone=A, first_num=None, second_chunk='', third_chunk=''
        # A,,1   -> zone=A, first_num=None, second_chunk='', third_chunk='1'
        # A,1,   -> zone=A, first_num=None, second_chunk='1', third_chunk=''
        # A,2,3   -> zone=A, first_num=None, second_chunk='2', third_chunk='3'
        if second_chunk is not None:
            if second_chunk:
                num1 = int(second_chunk)
        if third_chunk is not None:
            if third_chunk:
                num2 = int(third_chunk)
    elif third_chunk is None:
        # Cases:        
        # A1    -> zone=A, first_num='1', second_chunk None, third_chunk None
        # A2,3   -> zone=A, first_num='2', second_chunk='3', third_chunk None
        num1 = int(first_num)
        if second_chunk is not None:
            num2 = int(second_chunk)
    elif second_chunk is None:
        # Cases
        # A1,,3   -> zone=A, first_num='1', second_chunk='', third_chunk=''
        num1 = int(first_num)
        if third_chunk is not None:
            if third_chunk:
                num2 = int(third_chunk)
    
    return (base_zone, num1, num2)


if __name__ == "__main__":
    tests = [
        "A2,3",    # → ("B2",  "B3")
        "C11,12",  # → ("C11", "C12")
        "C11",     # → ("C11", None)
        "A,,10",   # → (None,  "A10")
        "A,3",     # → ("A3",  None)  (zone="A", number1=3)
        ",,,",     # → (None,  None)   (if someone typed zone="C" but no numbers)
    ]

    for t in tests:
        print(f"{t:8} => {parse_zone_numbers(t)}")
