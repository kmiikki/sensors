#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Dec 10 06:08:23 2024

@author: kim
"""
import pandas as pd
import argparse
import matplotlib.pyplot as plt
import os
import sys
from pathlib import Path

def get_input_file_path(base_dir, file):   
    # Search for analysis file in a directory tree
    dirs = ['', 'cal', 'cal/analysis']
    is_file = False
    for d in dirs:
        target = os.path.join(base_dir, d, file)
        if os.path.isfile(target):
            is_file = True
            break

    if not is_file:
        return None
    return target
    

def read_and_filter_data(file_path, threshold):
    # Read the CSV file into a DataFrame
    df = pd.read_csv(file_path)
    
    # Filter out rows where 'Sum of abs(slope)' exceeds the threshold
    df_filtered = df[df['Sum of abs(slope)'] <= threshold]
    
    return df_filtered

def analyze_column(data, col_mean_rhref, col_mean, targets):
    # Initialize the results list
    results = []
    seen_ranks = []
    
    #results.append((int(max_row['Rank']), max_row[col_mean_rhref], max_row[col_mean]))
    
    # Find the closest values to the target values excluding already seen ranks
    for target in targets:
        closest_row = data.iloc[(data[col_mean] - target).abs().argsort()[:1]].iloc[0]
        value = closest_row[col_mean]
        dist = abs(value - target)
        if dist > 5:
            continue
        if closest_row['Rank'] not in seen_ranks:
            results.append((int(closest_row['Rank']), closest_row[col_mean_rhref], closest_row[col_mean]))
            seen_ranks.append(closest_row['Rank'])

    # Combine and sort results
    results_sorted = sorted(results, key=lambda x: x[2])

    return results

def save_results_to_csv(results, file_path, value_col):
    headers = ['Rank', 'RHref%', value_col]
    df = pd.DataFrame(results, columns=headers)
    df.to_csv(file_path, index=False)
    
    # Create a text file without the Rank column but with headers
    txt_file_path = file_path.replace('.csv', '.txt')
    df_sorted = df[['RHref%', value_col]]
    df_sorted.to_csv(txt_file_path, index=False, header=True)

def plot_results(data, results, interval_col_start, interval_col_end, y_col, filename):
    fig, ax = plt.subplots()
    
    # Create the plot
    for row in results:
        rank, rhref, rh = row
        interval_start = data[data['Rank'] == rank][interval_col_start].values[0]
        interval_end = data[data['Rank'] == rank][interval_col_end].values[0]
        ax.hlines(y=rh, xmin=interval_start, xmax=interval_end, colors='r', linewidth=2)
    
    # Adding grid, labels, and title
    ax.grid(True, which='both', linestyle='--', linewidth=0.5)
    ax.set_xlabel('Measurement Number')
    ax.set_ylabel(f'{y_col}')
    ax.set_title('Calibration Levels')
    plt.yticks([i for i in range(0, 101, 10)])
    ax.set_ylim(0, 100)
    
    # Save the plot
    plt.savefig(filename, dpi=300)
    plt.close()
    
def main():
    analysis_dir = './analysis-rh'
    
    parser = argparse.ArgumentParser(description='Process RH Analysis Data.')
    parser.add_argument('file_path', type=str, help='Path to the CSV file.')
    parser.add_argument('-th', type=float, default=0.003, help='Threshold for "Sum of abs(slope)"')
    args = parser.parse_args()
    
    dir_path = str(Path(args.file_path).parent.absolute())
    file_name = Path(args.file_path).name
    file_path = get_input_file_path(dir_path, file_name)
    if file_path is None:
        print(f'File {file_name} not found.')
        sys.exit()
    
    # Read and filter the data
    df = read_and_filter_data(file_path, args.th)
    
    # Create analysis directory
    analysis_dir = Path(analysis_dir).absolute()
    analysis_dir.mkdir(parents=True, exist_ok=True)
    
    targets = list(range(0, 110, 10))
    
    # Analyze RH1% data and save results
    if 'Mean: RH1% (%)' in df.columns:
        results_rh1 = analyze_column(df, 'Mean: RHref (%RH)', 'Mean: RH1% (%)', targets)
        csv_file = os.path.join(analysis_dir, 'rh1-ranks.csv')
        save_results_to_csv(results_rh1, csv_file, 'RH1%')
        png_file = os.path.join(analysis_dir, 'rh1-cal-levels.png')
        plot_results(df, results_rh1, 'Interval start (s)', 'Interval end (s)', 'Mean: RH1% (%)', png_file)
    
    # Analyze RH2% data and save results if column exists
    if 'Mean: RH2% (%)' in df.columns:
        results_rh2 = analyze_column(df, 'Mean: RHref (%RH)', 'Mean: RH2% (%)', targets)
        csv_file = os.path.join(analysis_dir, 'rh2-ranks.csv')
        save_results_to_csv(results_rh2, csv_file, 'RH2%')
        png_file = os.path.join(analysis_dir, 'rh2-cal-levels.png')
        plot_results(df, results_rh2, 'Interval start (s)', 'Interval end (s)', 'Mean: RH2% (%)', png_file)

if __name__ == '__main__':
    main()
