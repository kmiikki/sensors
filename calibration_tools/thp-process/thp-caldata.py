#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct 30 12:32:58 2024

@author: Kim
"""

import pandas as pd
import argparse

def read_and_process_files(file1, file2, offset=0):
    # Read the first log file
    df1 = pd.read_csv(file1, encoding='utf-8')

    # Strip leading and trailing spaces from the column names
    df1.columns = df1.columns.str.strip()

    # Remove decimal parts of two first columns
    df1['Datetime'] = pd.to_datetime(df1['Datetime']).dt.strftime('%Y-%m-%d %H:%M:%S')
    df1['Timestamp'] = df1['Timestamp'].astype(int)
    
    # Read the second log file
    df2 = pd.read_csv(file2, encoding='utf-8')
    
    # Strip leading and trailing spaces from the column names
    df2.columns = df2.columns.str.strip()    
    
    # Apply offset if provided
    if offset:
        df2['Timestamp'] = df2['Timestamp'] - offset
    # Only keep necessary columns
    df2 = df2[['Timestamp', 'RH (%RH)', 'Temperature (°C)']]
    df2.rename(columns={'RH (%RH)': 'RHref (%RH)', 'Temperature (°C)': 'Tref (°C)'}, inplace=True)

    # Merge df1 and df2 based on the Timestamp column
    merged_df = pd.merge(df1, df2, on='Timestamp', how='left')
    
    return merged_df

def main():
    parser = argparse.ArgumentParser(description='Script to align log files based on timestamps and merge data.')
    parser.add_argument('file1', type=str, help='First log file')
    parser.add_argument('file2', type=str, help='Second log file')
    parser.add_argument('-o', '--offset', type=int, default=0, help='Offset in seconds to adjust from the second file timestamps')
    
    args = parser.parse_args()
    
    result_df = read_and_process_files(args.file1, args.file2, args.offset)
    
    output_file = 'merged-' + result_df['Datetime'][0].replace('-','').replace(' ','-').replace(':','') + '.csv'
    result_df.to_csv(output_file, index=False, encoding='utf-8')
    print(f'Result saved to {output_file}')

if __name__ == "__main__":
    main()
