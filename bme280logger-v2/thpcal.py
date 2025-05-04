#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Required files:
    bme280logger-v2.py
    thp_db.sql
    
Created on Mon Nov 11 12:40:32 2024
@author: Kim Miikki
"""
import argparse
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os
import re
import sqlite3
import shutil
import sys
from datetime import datetime
from pathlib import Path
from scipy import stats
from scipy.stats import t

# Print NumPy arrays without scientific notation
np.set_printoptions(suppress=True)

# Global variables
calibration_unit = None
calibration_text = None
is_before_menu = True

# Define the database file and schema file
db_file = 'calibration.db'
schema_file = 'thp_db.sql'
choices = {}


# Function to get Yes or No answer to a question
def input_yes_no(question, default=True):
    if default:
        default_ch = "Y"
    else:
        default_ch = "N"
    while True:
        try:
            tmp=input(f"{question} (Y/N, Default {default_ch}: <Enter>): ")        
            value=str(tmp).lower()
        except ValueError:
            print("Invalid input!")
            continue
        else:
            if (value == ""):
                if default:
                    value = "y"
                else:
                    value = "n"
            if value in ["y", "n"]:
                break
            print ("Select Y or N!")
            print("")
            continue
    if value == "y":
        return True
    else:
        return False


# Function to get MAC address of a Linux computer
def get_mac():
    dir = '/sys/class/net/'
    mac = ''
    try:
        interfaces = os.listdir(dir)
    except:
        pass
    
    try:
        for interface in interfaces:
            if interface[0].lower() in ['l', 'w']:
                continue
            mac = open(dir + interface + '/address').readline()
            break
    except:
        pass
    
    return mac[0:17]


# Function to get computer name
def get_computer_name():
    return os.uname()[1]


# Function to read and parse program arguments
def read_arguments():
    choices = {"file": "",
               "mac": "",
               "ref_sn": "",
               "zone": "",
               "sn": "",
               "gui": True}
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', help="calibration filename as input argument", type=str, required=False)
    parser.add_argument('-ref_sn', help="serial number of reference sensor", type=str, required=False)
    parser.add_argument('-s', help="sensor id (zone + number, e.g. A1)", type=str, required=False)
    args = parser.parse_args()
    
    if args.i != None:
        name = args.i
        name = name.strip()
        if not os.path.isfile(name):
            print("Input file not found. Program is terminated")
            sys.exit(1)
        choices["file"] = name
        
    if args.ref_sn != None:
        choices["ref_sn"] = args.ref_sn
    
    if args.s != None:
        s = args.s.strip().upper()
        
        # Check if only zone is present
        if s.isalpha():
            choices["zone"] = s
        else:       
            # Extract a string from start and number from end from the original string
            matches = re.search(r"^([A-Z]*)(\d+)$", s) 
            s_part = ""
            n_part = ""
            try:
                s_part, n_part = matches.groups()
            except:
                pass
    
            if len(n_part) > 0:
                choices["zone"] = s_part
                choices["sn"] = n_part
                
    return choices


# Function to create database from schema if it doesn't exist
def initialize_database(db_file, schema_file):
    db_exists = os.path.exists(db_file)
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    if not db_exists:
        with open(schema_file, 'r') as f:
            schema = f.read()
        cursor.executescript(schema)
        if is_before_menu:
            print("")
        print(f"Database ({db_file}) created from schema file.")
    conn.commit()
    if is_before_menu:
        print('')
    return conn, cursor


# Function to reinitialize the database
def reinitialize_database(db_file, schema_file):
    if os.path.exists(db_file):
        # Create backup of db_file before file removal (backup/db_file-stem-YYYYMMDD_hh:mm.db)
        os.remove(db_file)
    conn, cursor = initialize_database(db_file, schema_file)
    print(f"Database ({db_file}) reinitialized from schema file.")
    return conn, cursor


# Function to get computer name by mac 
def get_computer_by_mac(cursor, mac):
    cursor.execute("""
        SELECT name
        FROM computers
        WHERE mac = ?
    """, (mac,))
    result = cursor.fetchone()
    return result[0] if result else None


# Function to get zone by mac 
def get_zone_by_mac(cursor, mac):
    cursor.execute("""
        SELECT zone
        FROM sensors
        WHERE computers_id = ?
    """, (mac,))
    result = cursor.fetchone()
    return result[0] if result else None


# Function to insert computer name and mac into database
def insert_computer_mac_and_name(cursor, mac, name):
    cursor.execute("""
        INSERT INTO computers (mac, name)
        VALUES (?, ?)
    """, (mac, name))


# Function to update computer name in database
def update_computer_name(cursor, mac, name):
    cursor.execute("""
        UPDATE computers
        SET name = ?
        WHERE mac =?
    """, (name, mac))
        

# Function to update computer name in database
def update_computer_mac(cursor, mac, new_mac):
    cursor.execute("""
        UPDATE computers
        SET mac = ?
        WHERE mac =?
    """, (new_mac, mac))


# Function to get get all reference calibraton serial numbers
def get_ref_serial_numbers(cursor):
    cursor.execute("""
        SELECT serial_number
        FROM ref_sensors
    """)
    serials = [row[0] for row in cursor.fetchall()]
    return serials if serials else None


# Function to add a new reference sensor 
def add_ref_sensor(cursor):
    is_yes = input_yes_no("Add a new reference sensor")
    if not is_yes:
        print("A calibration sensor is required to run this program.")
        sys.exit(1)
    
    serial_number = input("Enter the S/N (serial number): ").strip()
    ref_name = input("Enter the sensor name: ")
    print("\nReference sensor:")
    print(f"S/N:  {serial_number}")
    print(f"Name: {ref_name}")
    print("")
    is_yes = input_yes_no("Add this sensor into database")
    if not is_yes:
        print("A calibration sensor is required to run this program.")
        sys.exit(1)
    
    cursor.execute("""
        INSERT INTO ref_sensors (serial_number, ref_name)
        VALUES (?, ?)
    """, (
        serial_number,
        ref_name
    ))
    
    return serial_number, ref_name

     
# Function to get last reference calibration date
def get_latest_ref_calibration_date(cursor, ref_sn_id):
    cursor.execute("""
        SELECT ref_calibration_date
        FROM ref_calibration_dates
        WHERE sn_id = ?
        ORDER BY ref_calibration_date DESC
        LIMIT 1
    """, (ref_sn_id,))
    result = cursor.fetchone()
    return result[0] if result else None


# Function to get last reference calibration date
def get_ref_calibration_dates(cursor, ref_sn_id):
    cursor.execute("""
        SELECT ref_calibration_date
        FROM ref_calibration_dates
        WHERE sn_id = ?
        ORDER BY ref_calibration_date ASC
    """, (ref_sn_id,))
    dates = [row[0] for row in cursor.fetchall()]
    return dates if dates else None


# Function to add last reference calibraton date to the reference sensor
def add_last_ref_cal_date(cursor, choices):
    global is_before_menu
    
    if is_before_menu:
        is_yes = input_yes_no("Add a calibration date for the reference sensor {choices['ref_sn']}")
        if not is_yes:
            print("A reference calibration date is required to run this program.")
            sys.exit(1)
    
    else:
        if not is_before_menu:
            print("New reference calibration date")

        ref_sn_id = choices['ref_sn']
        dates = get_ref_calibration_dates(cursor, ref_sn_id)
        while True:
            try:
                ref_date = input("Enter date (YYYY-MM-DD, 0 = Exit): ")
                if ref_date == "0":
                    break
                dt_obj = datetime.fromisoformat(ref_date)
                ref_date = dt_obj.date().isoformat()
                if dates is not None:
                    if ref_date in dates:
                        print("Given date is already in database!")
                        continue
                if not is_before_menu:
                    is_yes = input_yes_no(f"Add calibration date {ref_date} to reference sensor {ref_sn_id}?", False)
                if not is_yes:
                    break
                cursor.execute("""
                        INSERT INTO ref_calibration_dates (ref_calibration_date, sn_id)
                        VALUES (?, ?)
                    """, (
                        ref_date,
                        ref_sn_id
                    ))
                conn.commit()
                return True
            except:
                print("Illegal date format.")
        return False


# Function to check if sensor is in the database                
def is_sensor_in_db(cursor, choices):
    zone = choices['zone']
    sn = choices['sn']
    cursor.execute("""
        SELECT COUNT(*)
        FROM sensors
        WHERE zone = ? AND num = ?
    """, (zone, sn))
    result = cursor.fetchone()
    if result:
        if result[0] > 0:
            return True
        else:
            False
    else:
        return False


# Function to get last number in zone
def get_last_number_in_zone(cursor, choices):
    zone = choices['zone']
    ref_sn = choices["ref_sn"]
    cursor.execute("""
        SELECT num
        FROM sensors s
        LEFT JOIN ref_sensors r ON s.ref_sn_id = r.serial_number
        WHERE s.zone = ? AND s.ref_sn_id = ?
        ORDER BY num DESC
        LIMIT 1
    """, (zone, ref_sn,))
    result = cursor.fetchone()
    return result[0] if result else None


# Fetch mac by zone and sn     
def get_mac_from_sn(cursor, choices):
    zone = choices['zone']
    sn = choices['sn']
    cursor.execute("""
        SELECT computers_id
        FROM sensors
        WHERE zone = ? AND num = ?
    """, (zone, sn))
    result = cursor.fetchone()
    return result[0] if result else None


# List sensor numbers
def get_sensor_numbers(cursor, zone):
    cursor.execute("""
        SELECT num
        FROM sensors
        WHERE zone = ?
        ORDER BY num ASC
    """, (zone,))
    result = cursor.fetchall()
    numbers = [x[0] for x in result]
    return numbers


# Generate prompt string from ref_sn, zone and sn
def prompt_str(choices):
    ref_sn = choices['ref_sn']
    zone = choices['zone']
    sn = choices['sn']
    prompt = f"{ref_sn}: {zone}{sn}> "
    return prompt


# Find the nearest calibration date
def get_nearest_ref_calibration_date(cursor, date_str):
    ref_sn = choices["ref_sn"]
    cursor.execute("""
        SELECT MAX(ref_calibration_date)
        FROM ref_calibration_dates
        WHERE ref_calibration_date <= ?
    """, ( date_str,))
    result = cursor.fetchone()
    return result[0] if result else None

# -----------------------------------------------------------------------------

# Define functions for each operation


# Dsiplay all sensors in a zone
def list_sensors_in_zone(cursor, choices):
    zone = choices["zone"]
    ref_sn = choices["ref_sn"]
    print(f"Sensors in zone {zone} / reference sensor {ref_sn}:")
    
    cursor.execute("""
        SELECT s.num, c.name, s.type, s.address
        FROM sensors s
        LEFT JOIN computers c ON s.computers_id = c.mac
        LEFT JOIN ref_sensors r ON s.ref_sn_id = r.serial_number
        WHERE s.zone = ? AND s.ref_sn_id = ?
        ORDER BY s.num ASC
    """, (zone, ref_sn))
    result = cursor.fetchall()
    if len(result) > 0:
        max_length = len(str(result[-1][0]))
        for (number, name, type, address) in result:
            s = f"{str(number).rjust(max_length)}: "
            s += f"{name} | {type} | {hex(address)}"
            print(s)
    else:
        print("<EMPTY>")


# List all sensors
def list_all_sensors(cursor):
    print("Sensors in databse:")
    cursor.execute("""
        SELECT s.zone ,s.num, c.name, s.type, s.address
        FROM sensors s
        LEFT JOIN computers c ON s.computers_id = c.mac
        LEFT JOIN ref_sensors r ON s.ref_sn_id = r.serial_number
        ORDER BY s.zone, s.num ASC
    """)
    result = cursor.fetchall()
    if len(result) > 0:
        max_length = len(str(result[-1][0]))
        for (zone, number, name, type, address) in result:
            s = f"{str(number).rjust(max_length)}: "
            s += f"{zone}{number} | {name} | {type} | {hex(address)}"
            print(s)
    else:
        print("<EMPTY>")


# Select zone
def select_sensor(cursor, choices):
    zone = choices["zone"]
    print(f"Select sensor in zone {zone}")
    
    # Show list of sensor numbers
    print("\nValid sensor numbers:")
    numbers = list_numbers_by_zone(cursor, zone)
    if len(numbers) > 0:
        print(','.join([str(n) for n in numbers]))
    
    cursor.execute("""
        SELECT num
        FROM sensors
        WHERE zone = ?
        ORDER BY num ASC
    """, (zone,))
    result = cursor.fetchall()
    numbers = [x[0] for x in result]
    if len(numbers) == 0:
        print("<NO SENSORS>")
        return
    
    while True:
        try:
            number = input("Enter sensor number: ")
            number = int(number)
            if number not in numbers:
                print("Invalid selection. Valid numbers: ")
                print(",".join(map(str, numbers)))
                continue
            else:
                break
        except:
            print("Invalid number")
    choices["sn"] = str(number)


# Add sensor to a zone
def add_sensor(cursor, choices):
    def is_hex(s):
        try:
            int(s, 16)
            return True
        except ValueError:
            return False
    
    zone = choices["zone"]
    zone_length = len(zone)
    computers_id = choices["mac"]
    ref_sn = choices["ref_sn"]
    serials = get_sensor_numbers(cursor, zone)
    if len(serials) > 0:
        default_number = serials[-1] + 1
    else:
        default_number = 1
    default_len=len(str(default_number))
    
    print(f"Add a new sensor to zone {zone}")
    print(f"-------------------------{'-' * zone_length}")
    while True:
        try:
            name = input("Sensor name (e.g. BME280): ").strip()
            if len(name) == 0:
                print("Empty name is not accepted.")
                print('')
                continue
            try:
                sn = input("Address (e.g. 0x76)      : ").strip()
                # Test if number is hexcadecimal or normal number
                if sn[0:2] == "0x":
                    sn = int(sn, 16)
                else:
                    sn = int(sn, 10)
                if sn < 0:
                    print("Address must be 0 or a larger integer!")
                    continue
            except:
                print("Invalid address!")
                print("")
                continue
            n_str = f"Number (default: {str(default_number)}){' ' * (7 - default_len)}: "
            number =    input(n_str).strip() # spaces: 7 - default_len
            if number == "":
                number = default_number
            else:
                number = int(number)
            
            if number < 1:
                print('A positive sensor number is required.')
                print('')
                continue
            
            if number in serials:
                print("Duplicate S/N already exists!")
                print("")
                continue
            break
        except:
            print("")
     
    is_yes = input_yes_no(f"Add this sensor ({name}, {zone}{number}) into database")
    if not is_yes:
        return

    cursor.execute("""
        INSERT INTO sensors (zone, num, type, address, computers_id, ref_sn_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (zone, number, name, sn, computers_id, ref_sn
    ))
    conn.commit()
    print("Sensor added to database")
    if choices["sn"] == "":
        choices["sn"] = str(number)

# Delete sensor
def delete_sensor(cursor, choices):
    zone = choices['zone']
    sn = int(choices["sn"])
    print(f"Remove sensor from zone {zone}")
    try:
        number = input("Enter the number of the sensor to be deleted: ")
        number = int(number)
    except ValueError:
        print("Illegal or invalid number!")
        return
    
    if number == sn:
        print("Cannot remove active sensor!")
        return
    
    # Check if the sensor exists
    cursor.execute("""
        SELECT COUNT(*)
        FROM sensors
        WHERE zone = ? AND num = ?
    """, (zone, number))
    result = cursor.fetchone()
    if result:
        if result[0] > 0:
            cursor.execute("""
                DELETE FROM sensors
                WHERE zone = ? AND num = ?
            """, (zone, number))
            conn.commit()
            print("Sensor removed from database.")
            return
    print("Sensor not found in database.")


# Function to associate computer and sensor    
def assign_computer_to_sensor(cursor, choices):
    if choices["sn"] == "":
        print("Add a sensor before assignment.")
        return
    zone = choices['zone']
    is_sensor = True
    try:
        sn = int(choices['sn'])
    except ValueError:
        print("No selected sensors in zone {zone}.")
        print("")
        is_sensor = False
    
    if not is_sensor:
        numbers = list_numbers_by_zone(cursor, zone)
        count = len(numbers)
        if count == 1:
            sn = numbers[0]
        elif count > 1:
            sn = numbers[-1]
            print(f"Selecting last number in zone: {sn}")
        else:
            print('No sesnors in zone.')
            return
        
        choices['sn'] =sn

    print(f"Assign computer to zone {zone}")
    print(f"------------------------{'-' * len(zone)}")
    
    # List all computers
    query = """
        SELECT mac, name
        FROM computers
        ORDER BY mac, name;
    """
    cursor.execute(query)
    results = cursor.fetchall()
    
    # Convert to a dictionary
    mac_dict = {mac: name for mac, name in results}
    length = len(mac_dict)
    if length == 0:
        print("No computers in database.")
        return
    
    # Convert length to the number length
    length = len(str(length))
    
    # List the dictionary in selection format
    for idx, (mac, name) in enumerate(mac_dict.items(), start=1):
        print(f"{str(idx).rjust(length)}: {mac} | {name}")
        
    # Select computer by number
    try:
        number = input(f"Assign computer to sensor {zone}{sn} (0 = Exit): ").strip()
        number = int(number)
        if number == 0:
            return
        if number < 1 or number > idx:
            print("Selection out of range.")
            return
    except ValueError:
        print("Invalid selection.")
        return
    if number == 0:
        return
    
    # Get mac from selection
    mac = list(mac_dict.keys())[number - 1]
    
    # Update the sensor to assign the computer
    cursor.execute("""
        UPDATE sensors
        SET computers_id = ?
        WHERE zone = ? AND num = ?;
    """, (mac, zone, sn))
    
    conn.commit()


# Function to get a list of zones
def get_zones(cursor):
    cursor.execute("""
        SELECT zone
        FROM zones
        ORDER BY zone ASC
    """)
    result = cursor.fetchall()
    zones = [x[0] for x in result]
    return zones


# Function to add zone into database
def set_zone(cursor, zone):
    cursor.execute("""
        INSERT INTO zones (zone)
        VALUES (?)
    """, (
        zone,
    ))
    conn.commit()


# Function to print zones
def list_zones(cursor, choices):
    zones = get_zones(cursor)
    [print(x) for x in zones]
    

# Select number from a list of numbers
def select_number_from_list(numbers, name, exit_str = "0"):
    while True:
        try:
            select = input(f"Select {name} by number ({exit_str} = Exit): ").strip()
            if  select == exit_str:
                return None
            v = int(select)
            if v in numbers:
                return v
            print("Selection out of range. Valid numbers:")
            print(','.join([str(n) for n in numbers]))
        except:
            print("Invalid selection. Valid numbers:")
            print(','.join([str(n) for n in numbers]))
            
                         
# Select a zone frome a list of zones
def select_zone(cursor, choices):
    print("Select zone:")
    zones = get_zones(cursor)
    [print(x) for x in zones]
    while True:
        zone = input("Zone name (0 = Exit): ").strip()
        if zone == choices['zone']:
            print('Zone already selected.')
            return
        if zone == "0":
            return
        if zone in zones:
            # Get numbers for sensors in zone
            result = get_sensor_numbers(cursor, zone)
            if len(result) == 0:
                print(f"No sensors in zone {zone}")
                choices["sn"] = ''
                choices["zone"] = zone
                return
            choices["zone"] = zone
            break
        else:
            if is_before_menu:
                print("Invalid zone. A valid zone is required to run this program.")
                sys.exit(1)      
            print("Invalid zone.")
            return

    # List all sensors in the new zone, and select sensor number
    numbers = get_sensor_numbers(cursor, zone)
    if len(numbers) == 0:
        choices['sn'] = ''
        return
    elif len(numbers) == 1:
        choices['sn'] = numbers[0]
        return

    # Show list of sensor numbers
    print("\nValid sensor numbers:")
    print(','.join([str(n) for n in numbers]))
    zone = select_number_from_list(numbers, "sensor")
    if zone is not None:
        choices['sn'] = zone
    else:
        choices['sn'] = ''
        

# Fetch computers in a zone    
def list_computers_in_zone(cursor, choices):
    zone = choices['zone']
    print(f"Computers in zone {zone}:")
    
    # Execute the query
    query = """
        SELECT DISTINCT c.mac, c.name
        FROM sensors s
        JOIN computers c ON s.computers_id = c.mac
        WHERE s.zone = ?
        ORDER BY c.mac, c.name;
    """
    cursor.execute(query, (zone,))
    results = cursor.fetchall()
    for mac, name in results:
        print(f"{mac} | {name}")
    

# Function to add a zone into database
def add_zone(cursor, choices):
    zone = input("Enter zone name (0 = Exit): ").strip()
    zones = get_zones(cursor)

    if zone == "0":
        if is_before_menu:
            print("A zone is required to run this program.")
            sys.exit(1)
        return

    if zone == "":
        if is_before_menu:
            print("A zone is required to run this program.")
            sys.exit(1)
        else:
            return

    if zone in zones:
        print("Zone already exists!")
        print("")
        return
    
    # Accept the zone?
    is_yes = input_yes_no(f"Accept zone name {zone}")
    if not is_yes:
        if is_before_menu:
            print("")
            print("At least one zone is required to run this program.")
            sys.exit(1)
        else:
            return
    set_zone(cursor, zone)    
    print(f"Created zone {zone}")


# Functon to insert calibration meta data into database
def insert_calibration_date(cursor, calibration_date, label, name, name_ref, cal_unit, zone, num, ref_sn_id):
    insert_query = """
        INSERT INTO calibration_dates (
            calibration_date, label, name, name_ref, cal_unit, zone, num, ref_sn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """
    
    try:
        # Execute the insert query
        cursor.execute(insert_query, (calibration_date, label, name, name_ref, cal_unit, zone, num, ref_sn_id))
        
        # Commit the transaction
        conn.commit()
        
        # Get the last inserted ID (cal_id)
        cal_id = cursor.lastrowid        
        return cal_id
        
    except Exception as e:
        print(f"Error: {e}")
        return None


# Insert regression line data into database
def insert_regression_data(cursor, slope, const, r, r_squared, std_err, p_value, cal_id):
    insert_query = """
        INSERT INTO calibration_line (
            slope, const, r, r_squared, std_err, p_value, cal_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    
    try:
        # Execute the insert query
        cursor.execute(insert_query, (slope, const, r, r_squared, std_err, p_value, cal_id))
        
        # Commit the transaction
        conn.commit()
        
        # Get the last inserted ID (cal_id)
        cal_slopes_id = cursor.lastrowid        
        return cal_slopes_id
        
    except Exception as e:
        print(f"Error: {e}")
        return None


# Function to add calibration data into database
def insert_calibration_values(cursor, cal_id, data):
    insert_query = """
        INSERT INTO calibration_values (ref_value, sensor_value, cal_id)
        VALUES (?, ?, ?);
    """
    
    try:        
        # Insert data into the table
        for row in data:
            cursor.execute(insert_query, (row[0], row[1], cal_id))
        
        # Commit the transaction
        conn.commit()
        
        return True
    
    except Exception as e:
        print(f"Error: {e}")
        return False


# Fetch slope and const by cal_id
def get_slope_c(cursor, cal_id):
    query = """
        SELECT slope, const
        FROM calibration_line
        WHERE cal_id = ?;
    """
    cursor.execute(query, (cal_id,))
    result = cursor.fetchone()
    if result:
        slope, const = result
        return slope, const
    else:
        return None


# Fetch calibration values by cal_id
def get_calibration_values(cursor, cal_id):
    select_query = """
        SELECT ref_value, sensor_value
        FROM calibration_values
        WHERE cal_id = ?;
    """
    
    try:
        # Execute the query and fetch data
        cursor.execute(select_query, (cal_id,))
        rows = cursor.fetchall()
        
        # Convert the result to a NumPy array
        if rows:
            return np.array(rows, dtype=float)
        else:
            return None
    
    except Exception as e:
        print(f"Error: {e}")
        return None


# Fetch calibration dates
def get_calibration_dates_as_dict(cursor, zone, num):
    query = """
        SELECT cal_id, calibration_date, label
        FROM calibration_dates
        WHERE zone = ? AND num = ?
        ORDER BY calibration_date DESC;
    """
    
    try:      
        # Execute the query
        cursor.execute(query, (zone, num))
        rows = cursor.fetchall()
        
        # Transform the results into a dictionary format
        result_dict = {i + 1: [row[0], row[1], row[2]] for i, row in enumerate(rows)}
        
        return result_dict
    
    except Exception as e:
        print(f"Error: {e}")
        return {}


# Fetch calibration units
def get_calibration_units(cursor, cal_id):
    query = """
        SELECT label, name, name_ref, cal_unit
        FROM calibration_dates
        WHERE cal_id = ?;
    """
    try:        
        # Execute the query
        cursor.execute(query, (cal_id,))
        row = cursor.fetchone()
        
        # If data is found, create a dictionary
        if row:
            return {
                "label": row[0],
                "name": row[1],
                "name_ref": row[2],
                "cal_unit": row[3],
            }
        else:
            return None
        
    except Exception as e:
        print(f"Error: {e}")
        return None


# Fetch calibration labels by zone/number
def get_distinct_cal_labels(cursor, zone, num):
    query = """
        SELECT DISTINCT label
        FROM calibration_dates
        WHERE zone = ? AND num = ?;
    """    
    try:       
        # Execute the query
        cursor.execute(query, (zone, num))
        rows = cursor.fetchall()
        
        # Extract the distinct labels into a list
        return [row[0] for row in rows]
    
    except Exception as e:
        print(f"Error: {e}")
        return []


# Fetch a list of calibration dates by zone/vymber/label
def get_slopes_constants_dates(cursor, zone, num, label):
    query = """
        SELECT cl.slope, cl.const, cd.calibration_date
        FROM calibration_dates cd
        JOIN calibration_line cl ON cd.cal_id = cl.cal_id
        WHERE cd.zone = ? AND cd.num = ? AND cd.label = ?
        ORDER BY cd.calibration_date DESC
        LIMIT 10;
    """   
    try:
        # Execute the query
        cursor.execute(query, (zone, num, label))
        rows = cursor.fetchall()
        
        # Return the list of slopes and constants
        return rows
    
    except Exception as e:
        print(f"Error: {e}")
        return []


# Fetch linear regression values from the database
def get_regression_values(cursor, cal_id):
    query = """
        SELECT slope, const, r, r_squared, std_err, p_value
        FROM calibration_line
        WHERE cal_id = ?
    """
    cursor.execute(query, (cal_id,))
    result = cursor.fetchone()
    
    if result:
        # result: A tuple containing (slope, const, r, r_squared, std_err, p_value)
        return result
    else:
        raise ValueError(f"No regression values found for cal_id {cal_id}.")


# -----------------------------------------------------------------------------
# Calibration functions


# Function to parse units
def extract_values(text):
    pattern = re.compile(
        r'(%RH(?:ref|[1|2]?)\s*)|'
        r'(RH(?:ref|[1|2]?)%\s*)|'
        r'(([Tt](?:ref|[12]?))\s*[\[\(]°C[\]\)])|'
        r'(([Pp](?:ref|[12]?))\s*[\[\(]hPa[\]\)])'
    )

    match = pattern.match(text)
    
    if match:
        if match.group(1) or match.group(2):
            return match.group(0).strip(), ""
        elif match.group(3):
            return match.group(4), "°C"
        elif match.group(5):
            return match.group(6), "hPa"
    
    return None


# Function to perform lienar regression
def linear_regression(sensor_values, ref_values):
    slope, intercept, r, p_value, std_err = stats.linregress(sensor_values, ref_values)
    r_squared = r ** 2
    return slope, intercept, r, r_squared, std_err, p_value


# Function to compute fitted x, y values
def compute_fitted_xy(slope, intercept, xrange=(0, 100), steps=500):
    x_min = xrange[0]
    x_max = xrange[1]
    
    # Compute fitted values
    x_fit = np.linspace(x_min, x_max, steps)  # Interpolation and extrapolation range
    y_fit = slope * x_fit + intercept # Calculate fitted y values
    
    return x_fit, y_fit
 

# Function to calculate confidence intervals for the fitted x, y values
def ci_for_fitted_xy(xs, ys, slope, intercept, xrange=(0, 100), steps=500, alpha=0.05):
    x_min = xrange[0]
    x_max = xrange[1]
    
    # Compute fitted values
    x_fit, y_fit = compute_fitted_xy(slope, intercept, (x_min, x_max), steps)

    # Compute confidence intervals
    mean_x = np.mean(xs)
    n = len(xs)  # Number of calibrations
    dof = n - 2
    
    # t-value for alpha/2 with dof degrees of freedom
    t_value = t.ppf(1 - alpha / 2, dof)  
    
    # Residual standard error
    residuals = ys - (slope * xs + intercept)
    s_err = np.sqrt(np.sum(residuals**2) / dof)

    # Confidence interval computation
    ci = t_value * s_err * np.sqrt(
        1 / n + (x_fit - mean_x)**2 / np.sum((xs - mean_x)**2)
    )

    # Upper and lower bounds
    y_upper = y_fit + ci
    y_lower = y_fit - ci
    
    return y_lower, y_upper
    

# Function to parse units in a dataframe
def parse_units(df):
    dict = { "Error": [],
             "rows": 0,
             "name_ref" : "",
             "unit_ref" : "",
             "name" : "",
             "unit": "",
             "label": ""}
    
    is_ok = True    
    cols = df.columns
    if len(cols) != 2:
        dict["Error"].append("Invalid number of columns (must be 2)")
        is_ok = False
    
    # Check that header is present
    # Are column names numbers?
    if is_ok:
        floats = 0
        for i in range(2):            
            try:
                float(df.columns[i])
                floats += 1
            except ValueError:
                pass
        if floats > 0:
            # Header is not present
            dict["Error"].append("Invalid header")
            is_ok = False
    
    # Parse column names
    if is_ok:
        # Extract column names
        try:
            ref, ref_unit = extract_values(df.columns[0])
            sensor, sensor_unit = extract_values(df.columns[1])
        except TypeError:
            dict["Error"].append('Unable to extract valid column names')
            is_ok = False
        
        if is_ok:
            # Check for matches: ref <-> sensor and ref_unit <-> sensor_unit
            failures = 0
            
            l1 = len(ref)
            l2 = len(sensor)
    
            # Test RH%
            if l1 > 2 and l2 > 2:
                if ref[:2] != sensor[:2]:
                    failures += 1
                if ref[-1] != sensor[-1]:
                    failures += 1
            elif l1 > 0 and l2 > 0:
                # P, T tests
                if ref[0] != sensor[0]:
                    failures += 1
            
            # Test units
            if ref_unit != sensor_unit:
                failures += 1
            
            if failures > 0:
                dict["Error"].append(f"Failures in column names: {failures}")
                is_ok = False
    
    if is_ok:
        dict["name_ref"] = ref
        dict["unit_ref"] = ref_unit
        dict["name"] = sensor
        dict["unit"] = sensor_unit
    
    dict["rows"] = len(df)
    
    if is_ok:
        # Check validity of reference numbers
        for n in list(df.values[:,0]):
            try:
                float(n)
            except ValueError:
                dict["Error"].append("Invalid data in the reference column.")
                is_ok = False
                break
        # Check validity of sensor numbers
        for n in df.values[:,1]:
            try:
                float(n)
            except ValueError:
                dict["Error"].append("Invalid data in the sensor column.")
                is_ok = False
                break
    
    # Determine the type of calibration
    if is_ok:
        try:
            if dict["name_ref"][0:1].upper() == "T":
                dict["label"] = "Temperature"
            elif dict["name_ref"][0:1].upper() == "P":
                dict["label"] = "Pressure"
            if dict["name_ref"][0:2] == "RH":
                dict["label"] = "Relative Humidity"
        except:
            dict["Error"].append("Unable to extract the type of the sensor.")
            is_ok = False

    return dict

# Function to print the regression results to the terminal
def show_regression_results(slope, intercept, r, r_squared, std_err, p_value):
    print('Linear Regression Results:')
    print(f"  Formula: y = {slope:.4f}x", end="")
    if intercept < 0:
        s = ' - '
    elif intercept > 0:
        s = ' + '
    else:
        s = ''
    if s != '':
        s += str(f"{abs(intercept):.4f}")
    print(s)         
    print("")
    print(f"  Slope:          {slope:.4f}")
    print(f"  Intercept:      {intercept:.4f}")
    print(f"  R-value:        {r:.4f}")
    print(f"  R-squared:      {r_squared:.4f}")
    print(f"  Standard Error: {std_err:.4f}")
    print(f"  P-value:        {p_value:.4f}")


# Function to extract date / time info
def string_to_datetime(s):
    s = s.strip()
    
    # Get date and time parts
    parts = s.split(' ')
    
    # Check if date or date/time are present
    if len(parts) not in [1,2]:
        return None
    
    # Verify date part
    
    # yyyy-mm-dd (date) part
    s1 = parts[0].strip()
    x = re.search(r'^\d{4}\-(0?[1-9]|1[012])\-(0?[1-9]|[12][0-9]|3[01])$', s1)
    if not x:
        return None
    y, m, d = s1.split('-')
    y = int(y)
    m = int(m)
    d = int(d)
    hh = 0
    mm = 0
    ss = 0
    
    # hh:mm:ss (time) part
    if len(parts) == 2:
        s2 = parts[1].strip()
        
        # Check if hh:mm:ss format
        if re.search(r'^(2[0-3]|[01]?[0-9]):([0-5]?[0-9]):([0-5]?[0-9])$', s2):
            hh, mm, ss = s2.split(':')
            hh = int(hh)
            mm = int(mm)
            ss = int(ss)
        elif re.search(r'^(2[0-3]|[01]?[0-9]):([0-5]?[0-9])$', s2):
            hh, mm = s2.split(':')
            hh = int(hh)
            mm = int(mm)
        else:
            return None
    
    # Create a dt object
    dt = datetime(y, m, d, hh, mm, ss)
    
    return dt

# Extract datetime info from a calibration filename stem
def extract_datetime_from_end(s):
    s = s.strip()
       
    patterns = [
        # YYYY-MM-DD[ -T]HH:MM:SS
        r'(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})[ \-T](?P<h>\d{2}):(?P<min>\d{2}):(?P<s>\d{2})$',
        
        # YYYY-MM-DD[ -T]HHMMSS (no colons)
        r'(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})[ \-T](?P<h>\d{2})(?P<min>\d{2})(?P<s>\d{2})$',
        
        # YYYYMMDD-HHMMSS
        r'(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})[ \-T](?P<h>\d{2})(?P<min>\d{2})(?P<s>\d{2})$',
        
        # YYYY-MM-DD (no time)
        r'(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$',
        
        # YYYYMMDD (no separators, no time)
        r'(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$',
    ]
    
    for pat in patterns:
        match = re.search(pat, s)
        if match:
            gd = match.groupdict()
            y = int(gd['y'])
            m = int(gd['m'])
            d = int(gd['d'])
            
            # Default time
            hh = 0
            mm = 0
            ss = 0
            
            if 'h' in gd and gd['h'] is not None:
                hh = int(gd['h'])
            if 'min' in gd and gd['min'] is not None:
                mm = int(gd['min'])
            if 's' in gd and gd['s'] is not None:
                ss = int(gd['s'])
            
            # Validate date/time
            try:
                dt = datetime(y, m, d, hh, mm, ss)
                return dt
            except ValueError:
                # If date/time is invalid, continue to next pattern
                continue
    
    return None


# Function to add a new calibration to database from a calibration file
def new_calibration(cursor, choices):
    if choices["sn"] == "":
        print("Add a sensor before calibration.")
        return
    
    
    print("New calibration")
    print("---------------")
    
    filename = input("Enter calibration filename (0 = Exit): ")
    if filename == "0":
        return
    
    # Extract date/time from filename stem
    stem = Path(filename).stem
    dt = extract_datetime_from_end(stem)
    
    # Read the CSV file
    try:
        #df = pd.read_csv(filename, encoding='unicode_escape')
        df = pd.read_csv(filename, encoding='utf-8')
        df.columns = df.columns.str.strip()
    except:
        print(f"Unable to read file: {filename}")
        return
    
    # Extract units from the dataframe
    unit_dict = parse_units(df)
    
    if len(unit_dict["Error"]) > 0:
        for row in unit_dict["Error"]:
            print(row)
        return
    
    # Convert dataframe to a numpy array
    data = df.to_numpy()
    
    # Perform linear regression
    xs = data[:,1]
    ys = data[:,0]
    slope, intercept, r, r_squared, std_err, p_value = linear_regression(xs, ys)

    # Show results
    print('')
    show_regression_results(slope, intercept, r, r_squared, std_err, p_value)
    print('')

    if dt is None:        
        # Get current date
        dt = datetime.now()
    
    dt_str = dt.strftime('%Y-%m-%d %H:%M:%S')

    ask_dt_str = f"Enter calibration date ({dt_str} = Enter, 0 = Exit): "
    while True:
        try:
            new_dt = input(ask_dt_str).strip()
            if new_dt == '0':
                return
            elif new_dt == '':
                dt = string_to_datetime(dt_str)
                break
            dt = string_to_datetime(new_dt)
            if dt is None:
                print('Invalid date or datetime.\n')
                continue
            break
        except ValueError:
            print('Invalid date or datetime.\ŋ')
    
    # Insert record into calibration_date   
    calibration_date = dt.strftime("%Y-%m-%d %H:%M:%S")
    cal_date_short = dt.strftime("%Y-%m-%d")
    cal_unit = unit_dict["unit"]
    label = unit_dict["label"]
    name = unit_dict["name"]
    name_ref = unit_dict["name_ref"]
    zone = choices["zone"]
    sn = choices["sn"]
    ref_cal_id = choices["ref_sn"]
    last_date = get_nearest_ref_calibration_date(cursor, cal_date_short)
    if last_date is None:
        print("Warning: No prior reference calibration date!")
    cal_id = insert_calibration_date(cursor,
                                     calibration_date,
                                     label,
                                     name,
                                     name_ref,
                                     cal_unit,
                                     zone,
                                     sn,
                                     ref_cal_id)
    
    # Insert linear regression info into calibration_line table
    cal_slopes_id = insert_regression_data(cursor,
                                           slope,
                                           intercept,
                                           r,
                                           r_squared,
                                           std_err,
                                           p_value,
                                           cal_id)
    # print(cal_slopes_id)

    # Insert calibration data into calibration_values table
    result = insert_calibration_values(cursor, cal_id, data)
    if result:
        print("Calibration data inserted to database.")
    else:
        print("Unable to update databse.")


# Function to select a specific calibration 
def select_sensor_calibrations(cursor, zone, sn):
    print(f"{zone}{sn} sensor calibrations: ")
    dict = get_calibration_dates_as_dict(cursor, zone, sn)
    labels = get_distinct_cal_labels(cursor, zone, sn)
    if len(dict) == 0:
        print("<NONE>")
        return
    maxlen = 0
    dict_labels = {}
    for label in labels:
        if label == "Relative Humidity":
            dict_labels[label]="RH%"
        elif label == "Temperature":
            dict_labels[label]="°C"
        elif label == "Pressure":
            dict_labels[label]="hPa"
        else:
            dict_labels[label]= label
        if len(dict_labels[label]) > maxlen:
            maxlen = len(dict_labels[label])

    for key, value in dict.items():
        unit = dict_labels[value[2]]
        print(f"{str(key).rjust(2)} | {unit.ljust(maxlen)} | {value[1]}")
    
    print("")
    while True:
        try:
            select = input('Select calibration number (0 = Exit): ').strip()
            if select == "0":
                return {}
            select = int(select)
            if select < 1 or select > len(dict):
                print("Out of range.")
                continue
            break
        except ValueError:
            print("Invalid input.")
            
    # Get cal_id and date from dict
    cal_id = dict[select][0]
    sdate = dict[select][1]
    result = {"cal_id" : cal_id,
              "sdate"  : sdate}
    return result


# Generate and asve a calibration graph
def generate_calibration_graph(cursor, choices):
    zone = choices["zone"]
    sn = choices["sn"]
    print("Generate calibration graph")
    print("--------------------------")
    print("")

    dict_cal = select_sensor_calibrations(cursor, zone, sn)
    if len(dict_cal) == 0:
        return
    cal_id = dict_cal["cal_id"]
    sdate = dict_cal["sdate"][:len("yyyy-mm-dd")]
    
    # Get calibration points
    data = get_calibration_values(cursor, cal_id)
    if data is None:
        print("Calibration values not found.")
        return
    xs = data[:,1]
    ys = data[:,0]
    
    # Get line parameters
    slope, intercept = get_slope_c(cursor, cal_id)
    if slope is None or intercept is None:
        print("Missing regression data.")
        return
    
    unit_dict = get_calibration_units(cursor, cal_id)
    if unit_dict is None:
        print("Missing unit information.")
        return
    
    # Enable or disable minor grids
    has_minor_grid = input_yes_no("Enable minor grid")
    
    # Define x limits for plotting
    ustr= ''
    if unit_dict["label"] == "Relative Humidity":
        x_min = 0
        x_max = 100
        ustr = 'rh'
    elif unit_dict["label"] == "Temperature":
        x_min = -40
        x_max = 85
        ustr = 't'
    elif unit_dict["label"] == "Pressure":
        x_min = 300
        x_max = 1100
        ustr = 'p'
    else:
        x_min = np.min(xs)
        x_max = np.max(xs)
    
    # Compute fitted values
    x_fit, y_fit = compute_fitted_xy(slope, intercept, (x_min, x_max))
    
    # Compute CI values
    alpha = 0.05 # alpha for two-tailed CI
    ci_value = round(100 * (1 - alpha), 10)
    ci_lower, ci_upper = ci_for_fitted_xy(
                            xs, ys, slope, intercept, (x_min, x_max))
        
    # Define labels
    x_label = unit_dict["name"]
    y_label = unit_dict["name_ref"]
    if unit_dict["label"] in ["Temperature, Pressure"]:
        x_label += f" ({unit_dict['unit']}"
        y_label += f" ({unit_dict['unit_ref']}"
    
    # Plotting
    plt.figure(figsize=(10, 6))
    plt.scatter(xs, ys, label="Data Points", color="red", zorder=3)
    plt.xlim(x_min, x_max)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.title(f"{unit_dict['label']} - Sensor: {zone}{sn}, Calibration: {sdate}")
    
    # Draw gridlines
    if has_minor_grid:
        major_steps = 5
    else:
        major_steps = 10
    plt.grid(which='major', color='black', linestyle='--', linewidth=0.5, alpha=0.7)
    plt.xticks(np.arange(0, 101, major_steps))  # Major ticks every {major_steps}%
    plt.yticks(np.arange(0, 101, major_steps))  # Major ticks every {major_steps}%
    
    if has_minor_grid:
        plt.grid(which='minor', color='gray', linestyle=':', linewidth=0.5, alpha=0.5)
        plt.minorticks_on()
        plt.gca().xaxis.set_minor_locator(plt.MultipleLocator(1))  # Minor ticks every 1%
        plt.gca().yaxis.set_minor_locator(plt.MultipleLocator(1))  # Minor ticks every 1%
    
    plt.plot(x_fit, y_fit, color='k', label="Calibration Line (Linear Regression)", zorder=2)
    plt.fill_between(x_fit, ci_lower, ci_upper, color="gray", alpha=0.25, label=f"{ci_value}% Confidence Interval")
    plt.legend()
    plt.tight_layout()
    
    # Create filename for the graph
    if has_minor_grid:
        ustr += '-mg'
    filename = f"{zone}{sn}-cal{ustr}-{sdate[:len('yyyy-mm-dd')]}.png"
    plt.savefig(filename, dpi=300)
    plt.close()
    print(f"Calibration file {filename} created.")


# Function to select calibration type from the list of lables
def get_distinct_sensor_labels(cursor, zone, sn):
    # Check if there is any, one or many different calibration types / sensor
    label = ""
    labels = get_distinct_cal_labels(cursor, zone, sn)
    if len(labels) == 0:
        print(f"Calibrations not found for {zone}{sn}")
        return label
    
    if len(labels) == 1:
        label = labels[0]
    else:
        print("Select a calibration type from the list:")
        i = 1
        while i < len(labels):
            print(f"{i}: {labels[i-1]}")
            i += 1
        sel_min = 1
        sel_max = len(labels)
        while True:
            try:
                select = input("Select a number (0 = Exit): ").strip()
                if select == "0":
                    return label
                select = int(select)
                if select < sel_min or select > sel_max:
                    print("Selection out of range.")
                else:
                    label = labels[select - 1]
                    break
            except ValueError:
                print("Invalid number.")
    return label


# Plot multiple calibrations on one graph
def plot_all_calibrations(cursor, choices):
    zone = choices["zone"]
    sn = choices["sn"]
    
    print("Plot multiple calibrations for one sensor")
    print("-----------------------------------------")
    
    label = get_distinct_sensor_labels(cursor, zone, sn)
    if label == "":
        return
    
    pack = get_slopes_constants_dates(cursor, zone, sn, label)
    if len(pack) == 0:
        print("Regression data not found.")
        return
    
    # Define x limits for plotting
    ustr= ''
    lbl_str = ''
    if label == "Relative Humidity":
        x_min = 0
        x_max = 100
        lbl_str = 'RH%'
        ustr = 'rh'
    elif label == "Temperature":
        x_min = -40
        x_max = 85
        lbl_str = '°C'
        ustr = 't'
    elif label == "Pressure":
        x_min = 300
        x_max = 1100
        lbl_str = 'hPa'
        ustr = 'p'
    else:
        x_min = 0
        x_max = 100

    
    n = len(pack)  # Number of calibration lines
    colors = [(i/n * 0.8 + 0.2, i/n * 0.8 + 0.2, i/n * 0.8 + 0.2) for i in range(n+1)]  # Grayscale colors
    
    plt.figure(figsize=(10, 6))
    
    i = 0
    for (slope, const, date) in pack:
        
        # Generate X values for the plot
        x = np.linspace(x_min, x_max, 100)  # Fixed xmin and xmax
        
        # Calculate the calibration line
        y = slope * x + const
        
        # Plot the calibration line
        date_str = date[:len("yyyy-mm-dd")]
        plt.plot(x, y, color=colors[i], label=f"{date_str}", zorder=2 + (n - i))
        i += 1
    
    # Limit x-axes
    plt.xlim(x_min, x_max)
    
    # Add grid
    plt.grid(True)
    
    # Adding labels and title
    xlabel = "Sensor Value"
    ylabel = "Reference Value"
    if len(lbl_str) > 0:
        xlabel += f" ({lbl_str})"
        ylabel += f" ({lbl_str})"
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(f"{label} - Sensor: {zone}{sn}")
    plt.legend()
    plt.tight_layout()
        
    # Create filename for the graph save it
    date = pack[0][2]
    date = date[:len('yyyy-mm-dd')]
    filename = f"{zone}{sn}-caltime-{ustr}-{date}.png"
    plt.savefig(filename, dpi=300)
    print(f"Calibration graph {filename} created.")
    plt.close()
     

# Generate and export a calibration table
def export_calibration_table(cursor, choices):
    zone = choices["zone"]
    sn = choices["sn"]
    
    print("Export calibration table")
    print("------------------------")
    
    dict_cal = select_sensor_calibrations(cursor, zone, sn)
    if len(dict_cal) == 0:
        return
    cal_id = dict_cal["cal_id"]
    sdate = dict_cal["sdate"][:len("yyyy-mm-dd")]

    unit_dict = get_calibration_units(cursor, cal_id)
    label = unit_dict["label"]    
    slope, intercept = get_slope_c(cursor, cal_id)
    
    # Define x limits for the table
    sensor_str = ''
    cal_str= ''
    file_str = ''
    if label == "Relative Humidity":
        x_min = 0
        x_max = 100
        sensor_str = "RH%"
        cal_str = "RHcal%"
        file_str = "rh"
    elif label == "Temperature":
        x_min = -40
        x_max = 85
        sensor_str = "T (°C)"
        cal_str = "Tcal (°C)"
        file_str = "t"
    elif label == "Pressure":
        x_min = 300
        x_max = 1100
        sensor_str = "P (hPa)"
        cal_str = "Pcal (hPa)"
        file_str = "p"
    else:
        x_min = 0
        x_max = 100

    nums = x_max - x_min + 1
    xs = np.linspace(x_min, x_max, nums)
    ys = slope * xs + intercept
    ar = np.array([xs, ys])
    ar = ar.T # Transpose the array
    
    # Create a dataframe from the np.array
    df = pd.DataFrame(ar, columns = [sensor_str, cal_str])
    
    # Compose a name for the calibration table
    name = f"{zone}{sn}-cal{file_str}-{sdate}.csv"
    
    # Export calibration data to a csv file
    try:
        df.to_csv(name, index=False)
        print(f"Calibration file {name} exported.")
    except:
        print("Unable to export data to a csv file.")


# Two drirections calibration calculator
def calculator(cursor, choices):
    print("Calibration calculator")
    print("----------------------")
    
    zone = choices["zone"]
    sn = choices["sn"]
    decimals = 3
    
    # Select calibration date from zone+number
    dict_cal = select_sensor_calibrations(cursor, zone, sn)
    if len(dict_cal) == 0:
        return
    cal_id = dict_cal["cal_id"]
    
    # Get calibration parameters by cal_id
    dict_units = get_calibration_units(cursor, cal_id)
    slope, c = get_slope_c(cursor, cal_id)
        
    normal_direction = True
    print(f"Calculator mode: {dict_units['label']}")
    print("T = Toggle direction, x = Exit")
    # Run calculator
    while True:
        try:
            if normal_direction:
                prompt = "VAL -> CAL: "
            else:
                prompt = "CAL -> VAL: "
            ans = input(prompt).strip().upper()
            if ans == "X":
                return
            elif ans == "T":
                normal_direction = not normal_direction
                continue
            ans = float(ans)
            if normal_direction:
                v = ans * slope + c
            else:
                v = (ans - c) / slope
            v = round(v, decimals)
            print(v)
        except ValueError:
            print("Invalid input.")


# Get calibrated values array
def get_calibrated_array(xs, slope, c, decimals=2):
    cals = slope * xs + c
    cals = round(cals, decimals)
    return cals


# Calculate and add a column of calibrated valeus into a csv file
def batch(cursor, choices):
    print("Batch operation")
    print("---------------")
    
    zone = choices["zone"]
    sn = choices["sn"]
    decimals = 2
    
    # Select calibration date from zone+number
    dict_cal = select_sensor_calibrations(cursor, zone, sn)
    if len(dict_cal) == 0:
        return
    cal_id = dict_cal["cal_id"]
    
    # Get calibration parameters by cal_id
    dict_units = get_calibration_units(cursor, cal_id)
    slope, c = get_slope_c(cursor, cal_id)

    try:
        while True:
            filename = input('Filname for CSV data file (0 = Exit): ').strip()
            if filename == "0":
                return
            data_file = Path(filename)
            if data_file.is_file():
                break
            else:
                print("File not found.")
    except:
        print("Invalid file.")
        
    # Read the CSV file
    try:
        df = pd.read_csv(filename, encoding='utf-8')
        df.columns = df.columns.str.strip()
    except:
        print(f"Unable to read file: {filename}")
        return

    cols = list(df.columns)
    
    # Find columns where unit equals calibration unit
    results = {}
    i = 0
    label = dict_units["label"]
    for col in cols:
        result = extract_values(col)
        if result is not None:
            name, unit = result
            if name[0].upper() == label[0].upper():
                results[i] = [i+1, name, f"Cal: {name}"]
        i += 1

    if len(results) == 0:
        print('Data column not found.')
        return
    
    print("Select calibration column number: ")
    for k, v in results.items():
        print(f"{str(v[0]).rjust(2)}: {v[1]}") 
    while True:
        try:
            select = input('Enter column number (0 = Exit): ').strip()
            select = int(select) - 1
            if select not in list(results):
                print("Invalid column")
                continue
            break
        except ValueError:
            print("Invalin number")
            
    insert_label = results[select][2]
    insert_pos = results[select][0]
    
    # Calculate calibrated values
    cals = get_calibrated_array(df.iloc[:, select], slope, c, decimals)

    # Insert calibrated values into dataframe
    df.insert(insert_pos, insert_label, cals)   


    # Generate filename for the calibrated data
    sdate = dict_cal["sdate"][:len("yyyy-mm-dd")]
    
    
    # Save dataframe
    new_name = f"{Path(filename).stem}-{zone}{sn}-cal-{sdate}.csv"
    df.to_csv(new_name, index=False, header=True)
    print(f"File exported: {new_name}")


# Print a list of reference sensors
def list_reference_sensors(cursor, choices):
    print("Reference sensors:")
    cursor.execute("""
        SELECT ref_name, serial_number
        FROM ref_sensors
        ORDER BY ref_name ASC
    """,)
    sensors = cursor.fetchall()
    if len(sensors) > 0:
        max_len = len(max([s[0] for s in sensors], key=len))
        for name, sn in sensors:
            print(f"{name.ljust(max_len)}: {sn}")
    else:
        print("<NONE>")

# Function to add a reference sensor into database
def add_reference_sensor(cursor, choices):
    print("Add a new reference sensor to database")
    print("--------------------------------------")
    serials = get_ref_serial_numbers(cursor)
    try:
        name = input("Sensor name  : ").strip()
        sn =   input("Serial number: ").strip()
        if sn in serials:
            print("Duplicate S/N already exists!")
            return
    except:
        pass
    
    print("\nReference sensor:")
    print(f"S/N:  {sn}")
    print(f"Name: {name}")
    print("")
    is_yes = input_yes_no("Add this sensor into database")
    if not is_yes:
        return
    
    cursor.execute("""
        INSERT INTO ref_sensors (serial_number, ref_name)
        VALUES (?, ?)
    """, (
        sn,
        name
    ))
    conn.commit()
    
    # Assign a new calibration date to the reference sensor
    while True:
        try:
            ref_date = input("Enter date (YYYY-MM-DD): ")
            dt_obj = datetime.fromisoformat(ref_date)
            ref_date = dt_obj.date().isoformat()
            is_yes = input_yes_no(f"Add calibration date {ref_date} to reference sensor {sn}?", False)
            if not is_yes:
                continue
            cursor.execute("""
                    INSERT INTO ref_calibration_dates (ref_calibration_date, sn_id)
                    VALUES (?, ?)
                """, (
                    ref_date,
                    sn
                ))
            conn.commit()
            return
        except:
            print("Illegal date format.")
    

# Function to print a list of reference calibration dates    
def list_reference_calibration_dates(cursor, choices):
    print("Reference calibration dates:")
    ref_sn = choices["ref_sn"]
    cursor.execute("""
        SELECT ref_calibration_date
        FROM ref_calibration_dates
        WHERE sn_id = ?
        ORDER BY ref_calibration_date ASC
    """, (ref_sn,))
    result = cursor.fetchall()
    dates = [x[0] for x in result]
    if len(dates) > 0:
        for d in dates:
            print(d)
    else:
        print("<NO DATES>")


# Fetch computers as a dictionary
def get_computers(cursor):
    cursor.execute("""
        SELECT mac, name
        FROM computers
        ORDER BY name ASC
    """)
    result = cursor.fetchall()
    
    macs = []
    names = []
    for key, val in result:
        macs.append(key)
        names.append(val)
    computers = dict(zip(macs, names))
    return computers


# Function to print a list of computers 
def list_computers(cursor, choices):
    print("Computers:")
    computers = get_computers(cursor)
    for mac, v in computers.items():
        zone = get_zone_by_mac(cursor, mac)
        if zone is None:
            zone='-'
        s = f"{mac} | {zone} | {str(v)}"
        print(s)


# Validate a mac address string
def is_valid_mac(mac):
    if re.match("[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", mac.lower()):
        return True
    else:
        return False
    

# Function to add a computer to database    
def add_computer(cursor, choices):
    is_yes = input_yes_no("Add a new computer")
    if not is_yes:
        return
    
    name = input("Computer name: ").strip()
    mac  = input("MAC address  : ").strip()
    if not is_valid_mac(mac):
        print('Invalid MAC address.')
        return
    
    print("\nComputer:")
    print(f"Name: {name}")
    print(f"MAC : {mac}")
    print("")
    is_yes = input_yes_no("Add this computer into database")
    if not is_yes:
        return
    
    insert_computer_mac_and_name(cursor, mac, name)
    conn.commit()
    
    return


# Function to list macs by computer name
def list_macs_by_name(cursor, computer_name):
    cursor.execute("""
        SELECT mac
        FROM computers
        WHERE name = ?
        ORDER BY mac
    """, (computer_name,))
    result = cursor.fetchall()
    macs = [x[0] for x in result]
    return macs


# Fetch numbers in a zone
def list_numbers_by_zone(cursor, zone):
    cursor.execute("""
        SELECT num
        FROM sensors
        WHERE zone = ?
        ORDER BY num ASC
    """, (zone,))
    result = cursor.fetchall()
    numbers = [x[0] for x in result]
    return numbers


# Chack if name can be found in a zone
def is_name_in_zone(cursor, zone, name):   
    cursor.execute("""
        SELECT COUNT(c.name)
        FROM sensors s
        LEFT JOIN computers c ON s.computers_id = c.mac
        LEFT JOIN ref_sensors r ON s.ref_sn_id = r.serial_number
        WHERE s.zone = ?
        ORDER BY s.num ASC
    """, (zone))
    result = cursor.fetchone()
    return True if result else False


# Function to rename a computer
def rename_computer(cursor, choices):
    is_yes = input_yes_no("Rename a computer")
    name = input("Computer name: ").strip()
    macs = list_macs_by_name(cursor, name)
    print("")
    n = len(macs)
    if n == 0:
        print("Computer not found.")
        return
    
    if n == 1:
        number = 1
    else:
        # Show results
        for i in range(n):
            print(f"{i+1}: {macs[i]}")
        try:
            number = input("Select computer MAC by number: ").strip()
            number = int(number)
        except ValueError:
            print("Invalid number")
            return
        
    mac = macs[number-1]
    new_name = input("New name: ")
    if new_name == name:
        print("No need to rename.")
        return
    
    print("\nComputer:")
    print(f"Name: {name} -> {new_name}")
    print(f"MAC : {mac}")
    print("")
    is_yes = input_yes_no("Rename this computer")
    if not is_yes:
        return

    update_computer_name(cursor, mac, new_name)
    conn.commit()
    
    
# Function to alter a mac address
def change_computer_mac(cursor, choices):
    print("Changing computer MAC...")
    is_yes = input_yes_no("Change MAC address of a computer")
    name = input("Computer name: ").strip()
    macs = list_macs_by_name(cursor, name)
    print("")
    n = len(macs)
    if n == 0:
        print("Computer not found.")
        return
    
    if n == 1:
        number = 1
    else:
        # Show results
        for i in range(n):
            print(f"{i+1}: {macs[i]}")
        try:
            number = input("Select computer MAC by number: ").strip()
            number = int(number)
        except ValueError:
            print("Invalid number")
            return
        
    mac = macs[number-1]
    new_mac = input("New MAC address: ")
    if not is_valid_mac(new_mac):
        print("Invalid MAC address.")
        return
    
    if new_mac == mac:
        print("No need to rename.")
        return
    
    print("\nComputer:")
    print(f"Name: {name}")
    print(f"MAC : {mac} -> {new_mac}")
    print("")
    is_yes = input_yes_no("Change MAC address")
    if not is_yes:
        return

    update_computer_mac(cursor, mac, new_mac)
    conn.commit()
        
# -----------------------------------------------------------------------------    
# Database operations


# Backup the database
def backup_db(cursor, choices):
    # Get current working directory and create new filename
    cwd = os.getcwd()
    dt = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak_file = f"{cwd}/cal-{get_computer_name()}-{dt}.db"
    
    # Copy and rename the database file
    try:
        shutil.copy(db_file, bak_file)
        print("Database copied to:")
        print(bak_file)
    except:
        print("Unable to create a backup file of the database.")
    print("")

# Merge two dataqbases together
def merge_db(cursor, choices):
    global conn
    
    print("Merge database file into current database")
    print("-----------------------------------------")
    
    while True:
        try:
            merge_name = input("The name of the database to be merged with the current database: ").strip()
            if merge_name in ["", "0"]:
                print("Operation cancelled.")
                return
            if not os.path.isfile(merge_name):
                print("Input file not found.")
                continue
            break
        except:
            print("Invalid file name. Choose <Enter> or 0 to exit.!")
            continue

    # Close the database connection
    conn.close()
        
    # Connect to target database with a timeout
    conn = sqlite3.connect(db_file, timeout=10)
    cursor = conn.cursor()

    # Set a busy timeout at the database level
    cursor.execute("PRAGMA busy_timeout = 5000;")

    # Attach the source database
    cursor.execute(f"ATTACH DATABASE '{merge_name}' AS src")

    # Insert zones
    cursor.execute("""
        INSERT OR IGNORE INTO zones (zone)
        SELECT zone FROM src.zones;
    """)
    conn.commit()

    # Insert computers
    cursor.execute("""
        INSERT OR IGNORE INTO computers (mac, name)
        SELECT mac, name FROM src.computers;
    """)
    conn.commit()

    # Insert ref_sensors
    cursor.execute("""
        INSERT OR IGNORE INTO ref_sensors (serial_number, ref_name)
        SELECT serial_number, ref_name FROM src.ref_sensors;
    """)
    conn.commit()

    # Insert ref_calibration_dates (unique by date and sn)
    cursor.execute("""
    INSERT INTO ref_calibration_dates (ref_calibration_date, sn_id)
    SELECT ref_calibration_date, sn_id
    FROM src.ref_calibration_dates
    WHERE NOT EXISTS (
        SELECT 1 FROM ref_calibration_dates t
        WHERE t.ref_calibration_date = src.ref_calibration_dates.ref_calibration_date
        AND t.sn_id = src.ref_calibration_dates.sn_id
    );
    """)
    conn.commit()

    # Insert sensors
    cursor.execute("""
        INSERT OR IGNORE INTO sensors (zone, num, type, address, computers_id, ref_sn_id)
        SELECT zone, num, type, address, computers_id, ref_sn_id
        FROM src.sensors;
    """)
    conn.commit()

    # Insert calibration_dates with a uniqueness check
    cursor.execute("""
    INSERT INTO calibration_dates (calibration_date, label, name, name_ref, cal_unit, zone, num, ref_sn_id)
    SELECT s.calibration_date, s.label, s.name, s.name_ref, s.cal_unit, s.zone, s.num, s.ref_sn_id
    FROM src.calibration_dates s
    WHERE NOT EXISTS (
        SELECT 1 FROM calibration_dates t
        WHERE t.zone = s.zone
        AND t.num = s.num
        AND t.label = s.label
        AND t.calibration_date = s.calibration_date
    );
    """)
    conn.commit()

    # Insert calibration_values by mapping source cal_id to target cal_id
    cursor.execute("""
    INSERT INTO calibration_values (sensor_value, ref_value, cal_id)
    SELECT v.sensor_value, v.ref_value, t.cal_id
    FROM src.calibration_values v
    JOIN src.calibration_dates d ON v.cal_id = d.cal_id
    JOIN calibration_dates t ON t.zone = d.zone
                           AND t.num = d.num
                           AND t.label = d.label
                           AND t.calibration_date = d.calibration_date
    WHERE NOT EXISTS (
        SELECT 1 FROM calibration_values cv
        WHERE cv.sensor_value = v.sensor_value
          AND cv.ref_value = v.ref_value
          AND cv.cal_id = t.cal_id
    );
    """)
    conn.commit()

    # Insert calibration_line by mapping source cal_id to target cal_id
    cursor.execute("""
    INSERT INTO calibration_line (slope, const, r, r_squared, std_err, p_value, cal_id)
    SELECT l.slope, l.const, l.r, l.r_squared, l.std_err, l.p_value, t.cal_id
    FROM src.calibration_line l
    JOIN src.calibration_dates d ON l.cal_id = d.cal_id
    JOIN calibration_dates t ON t.zone = d.zone
                           AND t.num = d.num
                           AND t.label = d.label
                           AND t.calibration_date = d.calibration_date
    WHERE NOT EXISTS (
        SELECT 1 FROM calibration_line cl
        WHERE cl.slope = l.slope
          AND cl.const = l.const
          AND cl.r = l.r
          AND cl.r_squared = l.r_squared
          AND cl.std_err = l.std_err
          AND cl.p_value = l.p_value
          AND cl.cal_id = t.cal_id
    );
    """)
    conn.commit()

    # Detach and close
    cursor.execute("DETACH DATABASE src")
    conn.close()

    print(f"Database {merge_name} merged into {db_file}.")
    sys.exit(0)


# Function to delete current database
def delete_db(cursor, choices):
    print("Delete database")
    print("---------------")
    print("")
    try:
        s = input("Are you sure you want to delete the database (type Yes to proceed)? ")
        if s != "Yes":
            print("Operation cancelled.")
            return
    except:
        print("Invalid input.")
        return
    
    # Backup current database, delete it and exit the program
    backup_db(cursor, choices)
    conn.close()
    os.remove(db_file)
    print("The database was deleted. Restart the program to create a new database.")
    sys.exit(0)


# Function to delete a calibration by cal_id
def delete_calibration(cursor, choices):
    zone = choices["zone"]
    sn = choices["sn"]
    print("Delete calibration")
    print("------------------")
    print("")

    dict_cal = select_sensor_calibrations(cursor, zone, sn)
    if len(dict_cal) == 0:
        return
    cal_id = dict_cal["cal_id"]
    sdate =  dict_cal["sdate"]
    
    # Show calibration line data
    try:
        regression_values = get_regression_values(cursor, cal_id)
        show_regression_results(*regression_values)
    except:
        print("Calibration line data not found.")

    is_yes = input_yes_no(f"Delete calibration {sdate}", False)
    if not is_yes:
        return

    try:
        # Delete the record from calibration_dates
        cursor.execute("DELETE FROM calibration_dates WHERE cal_id = ?", (cal_id,))

        # Commit the changes
        conn.commit()
        print(f"Record with cal_id={cal_id} deleted successfully.")
    except sqlite3.Error as e:
        print(f"Error occurred: {e}")


# Print a list of reference sensors
def list_ref_sensors(cursor, choices):
    print("Reference sensors:")
    cursor.execute("""
        SELECT s.ref_name, s.serial_number, MAX(d.ref_calibration_date)
        FROM ref_sensors s, ref_calibration_dates d
        LEFT JOIN ref_calibration_dates ON s.serial_number = d.ref_cal_id
        ORDER BY s.ref_name ASC
    """,)
    sensors = cursor.fetchall()
    if len(sensors) > 0:
        max_len = len(max([s[0] for s in sensors], key=len))
        for name, sn, date in sensors:
            print(f"{name.ljust(max_len)} | {sn} | {date}")
    else:
        print("<NONE>")
    

# Print all zones    
def list_all_zones(cursor, choices):
   print("Zones:")
   list_zones(cursor, choices)


# Print a list of computers
def list_all_computers(cursor, zone):
    list_computers(cursor, choices)


# Print a list of sensors
def list_sensors(cursor, choices):
    list_all_sensors(cursor)

    
# Database Operations menu    
def database_operations(cursor, choices):
    def menu():
        rows = [
            "Database operations",
            "-------------------",
            "B   : Backup database to a file",
            "M   : Merge database from file",
            "DDb : Delete database",
            "DCal: Delete calibration",
            "",
            "List assets",
            "-----------",
            "R : Reference sensors",
            "Z : Zones",
            "C : Computers",
            "S : Sensors",
            "",
            "0 : Return to main menu"]
        [print(row) for row in rows]
    
    operations = {
        "B": backup_db,
        "M": merge_db,
        "DDb": delete_db,
        "DCal": delete_calibration,
        "R": list_ref_sensors,
        "Z": list_all_zones,
        "C": list_all_computers,
        "S": list_sensors,
    }  
    
    print("")
    while True:
        menu()
        print("")
        try:
            select = input("Operation> ").strip()
            if select == "":
                print("")
                continue
            
            elif select == "0":
                return
            elif len(select) == 1:
                select = select.upper()
            
            # Check if select is in dictionary
            if select in operations:
                print("")
                operations[select](cursor, choices)
                print("")
                continue
            print("")
        except ValueError:
            print("Invalid input.\n")


# -----------------------------------------------------------------------------

# Main menu
def print_menu(cursor, choices):
    column1 = {
        "SENSORS": ["L: List sensors in zone", "S: Select sensor", "A: Add sensor", "D: Delete sensor"],
        "ZONES": ["ZL: List zones", "ZS: Select zone", "ZA: Add zone", "ZC: List computers in zone"],
        "CALIBRATION": ["C: New calibration", "G: Generate calibration graph", "P: Plot all calibrations for one sensor", 
                        "E: Export calibration table", "V: Calibration calculator", "B: Batch operation"]
    }

    column2 = {
        "REFERENCE SENSORS": ["RL: List reference sensors", "RA: Add reference sensor", "RD: List calibration dates", "RC: New calibration date"],
        "COMPUTERS": ["CL: List computers", "CA: Add computer", "CR: Rename computer", "CM: Change computer MAC", "CC: Assign computer to sensor"],
        "MISC": ["DB: Database operations", "M, H, ?: Print selection menu", "X, 0   : Exit program"]
    }

    col1_keys = list(column1.keys())
    col2_keys = list(column2.keys())
    
    max_length = max(len(col1_keys), len(col2_keys))

    print("")
    for i in range(max_length):
        if i < len(col1_keys):
            key1 = col1_keys[i]
            print("{:<40}".format(key1), end="")
        else:
            print("{:<40}".format(" "), end="")

        if i < len(col2_keys):
            key2 = col2_keys[i]
            print("{}".format(key2))
        else:
            print("")
        if i < len(col1_keys):
            for item in column1[key1]:
                print("{:<40}".format(item), end="")
                if i < len(col2_keys) and len(column2[col2_keys[i]]) > 0:
                    print("{}".format(column2[col2_keys[i]].pop(0)))
                else:
                    print("")
        
        if i < len(col2_keys) and len(column2[key2]) > 0:
            for item in column2[key2]:
                print("{:<40}{}".format("", item))
        if i < max_length - 1:
            print("")

# Main program
def main():
    global db_file
    global schema_file
    global choices
    global is_before_menu
    global conn

    print("THP Sensor Calibration")
    print("Kim Miikki, 2024")
    
    # Initialize the database
    db_file = os.path.dirname(__file__) + "/" + db_file
    schema_file = os.path.dirname(__file__) + "/" + schema_file
    conn, cursor = initialize_database(db_file, schema_file)
    
    # Parse arguments
    choices = read_arguments()

    # Check if zone exists in the database
    zones = get_zones(cursor)
    zone = choices["zone"]
    numbers = len(zones)
    if numbers == 0:
        print("Creating a new zone.")
        print("--------------------")
        add_zone(cursor, choices)  
        print("")
    
        # Refresh zones list
        zones = get_zones(cursor)
        zone = zones[0]
        choices["zone"] = zone
    else:
        if zone in zones:
            print(f"Zone {zone} found.")
            choices["zone"] = zone
        elif numbers == 1:
             choices["zone"] = zones[0]
        else:
            select_zone(cursor, choices)
            print("")
        
    # Check if the computer exists in the database
    mac = get_mac().lower()
    cname = get_computer_name()
    cname_lookup = get_computer_by_mac(cursor, mac)
    if cname_lookup is None:
        print(f"Adding {cname} into database.")
        print('')
        insert_computer_mac_and_name(cursor, mac, cname)
        conn.commit()
    elif cname_lookup != cname:
        print(f"Updating {cname_lookup} -> {cname} in database.")
        update_computer_name(cursor, mac, cname)
        conn.commit()

    # Check if there is a reference sensor, add one if it is missing from the database
    ref_serials = get_ref_serial_numbers(cursor)
    if ref_serials is None:
        serial_number, ref_name = add_ref_sensor(cursor)
        conn.commit()
        ref_serials = get_ref_serial_numbers(cursor)
    is_before_menu = False
    
    if choices['ref_sn'] not in ref_serials:
        if len(choices['ref_sn']) > 0:
            print(f"Reference serial number {choices['ref_sn']} is not in database.")
        if len(ref_serials) == 1:
            print(f"Automatically selected the only S/N in database: {ref_serials[0]}")
            choices['ref_sn'] = ref_serials[0]
        elif len(ref_serials) > 1:
            print("Sensors:")
            i = 0
            while i < len(ref_serials):
                print(f"{str(i+1).rjust(2)}: {ref_serials[i]}")
                i += 1
            number = 0
            number_min = 1
            number_max = len(ref_serials)
            while True:
                try:
                    select = input(f"Select reference sensor ({number_min}-{number_max}, 0 = Exit): ").strip()
                    number = int(select)
                except:
                    pass
                else:
                    if number == 0:
                        print("Program is terminated.")
                        sys.exit(0)
                    elif number < 1 or number > number_max:
                        print("Out of range.")
                        continue
                    choices["ref_sn"] = ref_serials[number-1]
                    break
    
    # Check if sensor exists, if not try to select the last sensor
    is_sensor = is_sensor_in_db(cursor, choices)
    if not is_sensor:
        number = get_last_number_in_zone(cursor, choices)
        if number is not None:
            choices['sn'] = str(number)
        else:
            choices['sn'] = ""            
    
    # Get MAC from database
    if choices['sn'] != "":
        result = get_mac_from_sn(cursor, choices)
        if result is not None:
            choices["mac"] = result
    
    # Check if reference calibration date exist, and select the last
    # or add a date
    last_ref_cal_date = get_latest_ref_calibration_date(cursor, choices["ref_sn"])
    if last_ref_cal_date is None:
        print("")
        change = add_last_ref_cal_date(cursor, choices)
        if change:
            conn.commit()

    operations = {
        "L": list_sensors_in_zone,
        "S": select_sensor,
        "A": add_sensor,
        "D": delete_sensor,
        "ZL": list_zones,
        "ZS": select_zone,
        "ZA": add_zone,
        "ZC": list_computers_in_zone,
        "C": new_calibration,
        "G": generate_calibration_graph,
        "P": plot_all_calibrations,
        "E": export_calibration_table,
        "V": calculator,
        "B": batch,
        "RL": list_reference_sensors,
        "RA": add_reference_sensor,
        "RD": list_reference_calibration_dates,
        "RC": add_last_ref_cal_date,
        "CL": list_computers,
        "CA": add_computer,
        "CR": rename_computer,
        "CM": change_computer_mac,
        "CC": assign_computer_to_sensor,
        "DB": database_operations,
        "M": print_menu,
        "H": print_menu,
        "?": print_menu
    }        
    
    if choices['gui']:
        print_menu(cursor, choices)
        print("")
        while True:
            select = input(f"{prompt_str(choices)}").strip().upper()
            if select in ["X", "0"]:
                print("Exiting program...")
                break
            elif select in operations:
                operations[select](cursor, choices)
                print("")
            else:
                print("Invalid selection (M, H, ?: display menu)")
                print("")
        
    # Close db connection and exit program
    if 'conn' in locals():
        conn.close()

if __name__ == "__main__":
    get_mac()
    main()
