#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
from scipy.stats import linregress
import matplotlib.pyplot as plt
import os
import argparse

def calculate_slope(y, x):
    slope, intercept, r_value, p_value, std_err = linregress(x, y)
    return slope

def analyze_intervals(df, interval_size, window_size, has_sensor2):
    num_intervals = len(df) // interval_size
    results = []
    
    for i in range(num_intervals):
        start_idx = i * interval_size
        end_idx = min(start_idx + window_size, len(df))
        interval_df = df.iloc[start_idx:end_idx]
        x = interval_df['Time (s)']
        
        slopes = {}
        means = {}
        mins = {}
        maxs = {}

        columns = ['Tref (°C)', 't1 (°C)', 'RHref (%RH)', 'RH1% (%)', 'p1 (hPa)']
        if has_sensor2:
            columns.extend(['t2 (°C)', 'RH2% (%)', 'p2 (hPa)'])
        
        for col in columns:
            y = interval_df[col]
            slopes[f'Slope: {col}'] = calculate_slope(y, x)
            means[col] = y.mean()
            mins[col] = y.min()
            maxs[col] = y.max()
        
        result = {
            'Interval start (s)': x.iloc[0],
            'Interval end (s)': x.iloc[-1]
        }
        result.update(slopes)
        result.update({f'Mean: {k}': v for k, v in means.items()})
        result.update({f'Min: {k}': v for k, v in mins.items()})
        result.update({f'Max: {k}': v for k, v in maxs.items()})
        
        results.append(result)
        
    return results

def sort_and_save_results(results, filename, sort_keys, header):
    sorted_results = sorted(results, key=lambda x: sum(abs(x[f'Slope: {key}']) for key in sort_keys))
    sorted_df = pd.DataFrame(sorted_results)
    header_fields = header.split(', ')[:3]  # Always include rank, interval start, and interval end
    header_fields.extend([field for field in header.split(', ')[3:] if field in sorted_df.columns])
    sorted_df.insert(0, "Rank", range(1, 1 + len(sorted_df)))
    sorted_df = sorted_df[header_fields]
    sumsabs_df = sorted_df.filter(regex='^Slope:').abs().sum(axis=1)
    sorted_df.insert(3, "Sum of abs(slope)", sumsabs_df)
    sorted_df.to_csv(filename, index=False, float_format='%.6f')
    return sorted_df  # Return the sorted dataframe to add ranks

def plot_and_save_graphs(df, analysis_path, has_sensor2):
    plt.figure(figsize=(12, 8), dpi=300)

    plt.subplot(3, 1, 1)
    plt.plot(df['Time (s)'], df['Tref (°C)'], label='Tref')
    plt.plot(df['Time (s)'], df['t1 (°C)'], label='t1')
    if has_sensor2:
        plt.plot(df['Time (s)'], df['t2 (°C)'], label='t2')
        plt.title('Tref, t1, t2')
    else:
        plt.title('Tref, t1')
    plt.legend()
    

    plt.subplot(3, 1, 2)
    plt.plot(df['Time (s)'], df['RHref (%RH)'], label='RHref')
    plt.plot(df['Time (s)'], df['RH1% (%)'], label='RH1')
    if has_sensor2:
        plt.plot(df['Time (s)'], df['RH2% (%)'], label='RH2')
        plt.title('RHref, RH1, RH2')
    else:
        plt.title('RHref, RH1')
    plt.legend()
    
    plt.subplot(3, 1, 3)
    plt.plot(df['Time (s)'], df['p1 (hPa)'], label='p1')
    if has_sensor2:
        plt.plot(df['Time (s)'], df['p2 (hPa)'], label='p2')
        plt.title('p1, p2')
    else:
        plt.title('p1')        
    plt.legend()

    plt.tight_layout()
    plt.savefig(f'{analysis_path}/combined_thp_by_time.png')
    plt.close()

def plot_slope_graphs(df_results, analysis_path, has_sensor2):
    num_intervals = len(df_results)

    # RH Slopes by Time
    if has_sensor2:
        subplots = 3
    else:
        subplots = 2
    fig, ax = plt.subplots(subplots, 1, figsize=(10, 15))
    ax[0].plot(df_results['Interval start (s)'], df_results['Slope: RHref (%RH)'], label='RHref Slope', color='b')
    ax[0].legend()
    ax[0].set_title('RHref Slope by Time')
    ax[0].set_xlabel("Time (s)")
    ax[0].set_ylabel("Slope")

    ax[1].plot(df_results['Interval start (s)'], df_results['Slope: RH1% (%)'], label='RH1 Slope', color='r')
    ax[1].legend()
    ax[1].set_title('RH1 Slope by Time')
    ax[1].set_xlabel("Time (s)")
    ax[1].set_ylabel("Slope")

    if has_sensor2:
        ax[2].plot(df_results['Interval start (s)'], df_results['Slope: RH2% (%)'], label='RH2 Slope', color='g')
        ax[2].legend()
        ax[2].set_title('RH2 Slope by Time')
        ax[2].set_xlabel("Time (s)")
        ax[2].set_ylabel("Slope")
    plt.tight_layout()
    plt.savefig(f'{analysis_path}/combined_rh_slopes_by_time.png', dpi=300)
    plt.close()

    # RH Slopes by Rank
    fig, ax = plt.subplots(subplots, 1, figsize=(10, 15))
    rank_range = range(1, num_intervals + 1)
    
    ax[0].plot(rank_range, sorted(df_results['Slope: RHref (%RH)'], key=abs), label='RHref Slope', color='b')
    ax[0].legend()
    ax[0].set_title('RHref Slope by Rank')
    ax[0].set_xlabel("Rank")
    ax[0].set_ylabel("Slope")

    ax[1].plot(rank_range, sorted(df_results['Slope: RH1% (%)'], key=abs), label='RH1 Slope', color='r')
    ax[1].legend()
    ax[1].set_title('RH1 Slope by Rank')
    ax[1].set_xlabel("Rank")
    ax[1].set_ylabel("Slope")

    if has_sensor2:
        ax[2].plot(rank_range, sorted(df_results['Slope: RH2% (%)'], key=abs), label='RH2 Slope', color='g')
        ax[2].legend()
        ax[2].set_title('RH2 Slope by Rank')
        ax[2].set_xlabel("Rank")
        ax[2].set_ylabel("Slope")
    plt.tight_layout()
    plt.savefig(f'{analysis_path}/combined_rh_slopes_by_rank.png', dpi=300)
    plt.close()

    # Temperature Slopes by Time
    fig, ax = plt.subplots(subplots, 1, figsize=(10, 15))
    ax[0].plot(df_results['Interval start (s)'], df_results['Slope: Tref (°C)'], label='Tref Slope', color='b')
    ax[0].legend()
    ax[0].set_title('Tref Slope by Time')
    ax[0].set_xlabel("Time (s)")
    ax[0].set_ylabel("Slope")

    ax[1].plot(df_results['Interval start (s)'], df_results['Slope: t1 (°C)'], label='t1 Slope', color='r')
    ax[1].legend()
    ax[1].set_title('t1 Slope by Time')
    ax[1].set_xlabel("Time (s)")
    ax[1].set_ylabel("Slope")

    if has_sensor2:
        ax[2].plot(df_results['Interval start (s)'], df_results['Slope: t2 (°C)'], label='t2 Slope', color='g')
        ax[2].legend()
        ax[2].set_title('t2 Slope by Time')
        ax[2].set_xlabel("Time (s)")
        ax[2].set_ylabel("Slope")
    plt.tight_layout()
    plt.savefig(f'{analysis_path}/combined_temp_slopes_by_time.png', dpi=300)
    plt.close()

    # Temperature Slopes by Rank
    fig, ax = plt.subplots(subplots, 1, figsize=(10, 15))
    ax[0].plot(rank_range, sorted(df_results['Slope: Tref (°C)'], key=abs), label='Tref Slope', color='b')
    ax[0].legend()
    ax[0].set_title('Tref Slope by Rank')
    ax[0].set_xlabel("Rank")
    ax[0].set_ylabel("Slope")

    ax[1].plot(rank_range, sorted(df_results['Slope: t1 (°C)'], key=abs), label='t1 Slope', color='r')
    ax[1].legend()
    ax[1].set_title('t1 Slope by Rank')
    ax[1].set_xlabel("Rank")
    ax[1].set_ylabel("Slope")

    if has_sensor2:
        ax[2].plot(rank_range, sorted(df_results['Slope: t2 (°C)'], key=abs), label='t2 Slope', color='g')
        ax[2].legend()
        ax[2].set_title('t2 Slope by Rank')
        ax[2].set_xlabel("Rank")
        ax[2].set_ylabel("Slope")
    plt.tight_layout()
    plt.savefig(f'{analysis_path}/combined_temp_slopes_by_rank.png', dpi=300)
    plt.close()

    # Pressure Slopes by Time
    if has_sensor2:
        fig, ax = plt.subplots(subplots - 1, 1, figsize=(10, 10))
        ax[0].plot(df_results['Interval start (s)'], df_results['Slope: p1 (hPa)'], label='p1 Slope', color='b')
        ax[0].legend()
        ax[0].set_title('p1 Slope by Time')
        ax[0].set_xlabel("Time (s)")
        ax[0].set_ylabel("Slope")

        ax[1].plot(df_results['Interval start (s)'], df_results['Slope: p2 (hPa)'], label='p2 Slope', color='r')
        ax[1].legend()
        ax[1].set_title('p2 Slope by Time')
        ax[1].set_xlabel("Time (s)")
        ax[1].set_ylabel("Slope")

        name = f'{analysis_path}/combined_pressure_slopes_by_time.png'
    else:
        plt.figure()
        plt.plot(df_results['Interval start (s)'], df_results['Slope: p1 (hPa)'], label='p1 Slope', color='b')
        plt.title('p1 Slope by Time')
        plt.xlabel("Time (s)")
        plt.ylabel("Slope")

        name = f'{analysis_path}/pressure_slope_by_time.png'
    plt.tight_layout()
    plt.savefig(name, dpi=300)
    plt.close()

    # Pressure Slopes by Rank
    if has_sensor2:
        fig, ax = plt.subplots(subplots - 1, 1, figsize=(10, 10))
        ax[0].plot(rank_range, sorted(df_results['Slope: p1 (hPa)'], key=abs), label='p1 Slope', color='b')
        ax[0].legend()
        ax[0].set_title('p1 Slope by Rank')
        ax[0].set_xlabel("Rank")
        ax[0].set_ylabel("Slope")

        ax[1].plot(rank_range, sorted(df_results['Slope: p2 (hPa)'], key=abs), label='p2 Slope', color='r')
        ax[1].legend()
        ax[1].set_title('p2 Slope by Rank')
        ax[1].set_xlabel("Rank")
        ax[1].set_ylabel("Slope")

        name = f'{analysis_path}/combined_pressure_slopes_by_rank.png'
    else:
        plt.figure()
        plt.plot(rank_range, df_results['Slope: p1 (hPa)'], label='p1 Slope', color='b')
        plt.title('p1 Slope by Rank')
        plt.xlabel("Rank")
        plt.ylabel("Slope")

        name = f'{analysis_path}/pressure_slope_by_rank.png'

    plt.tight_layout()
    plt.savefig(name, dpi=300)
    plt.close()

def main():
    parser = argparse.ArgumentParser(description="Analyzes flat intervals in sensor measurements.")
    parser.add_argument('filename', nargs='?', default='thp.csv', help='The CSV file containing the measurements.')
    parser.add_argument('-i', '--interval', type=int, default=50, help='The interval size for measurement analysis. Default is 50.')
    parser.add_argument('-w', '--window', type=int, default=50, help='The window size for comparison. Default is 50.')

    args = parser.parse_args()
    file_path = args.filename
    interval_size = args.interval
    window_size = args.window

    analysis_path = 'analysis'
    os.makedirs(analysis_path, exist_ok=True)

    df = pd.read_csv(file_path, encoding='unicode_escape')

    # Strip leading and trailing spaces from the column names
    df.columns = df.columns.str.strip()
    df.columns = [col.encode('latin1').decode('utf-8') for col in df.columns]

    # Determine if sensor 2 data is present
    has_sensor2 = 't2 (°C)' in df.columns and 'RH2% (%)' in df.columns and 'p2 (hPa)' in df.columns

    results = analyze_intervals(df, interval_size, window_size, has_sensor2)

    # Headers and keys based on presence of sensor 2
    if has_sensor2:
        temperature_header = 'Rank, Interval start (s), Interval end (s), Slope: Tref (°C), Slope: t1 (°C), Slope: t2 (°C), Mean: Tref (°C), Mean: t1 (°C), Mean: t2 (°C), Min: Tref (°C), Max: Tref (°C), Min: t1 (°C), Max: t1 (°C), Min: t2 (°C), Max: t2 (°C)'
        rh_header = 'Rank, Interval start (s), Interval end (s), Slope: RHref (%RH), Slope: RH1% (%), Slope: RH2% (%), Mean: RHref (%RH), Mean: RH1% (%), Mean: RH2% (%), Min: RHref (%RH), Max: RHref (%RH), Min: RH1% (%), Max: RH1% (%), Min: RH2% (%), Max: RH2% (%)'
        pressure_header = 'Rank, Interval start (s), Interval end (s), Slope: p1 (hPa), Slope: p2 (hPa), Mean: p1 (hPa), Mean: p2 (hPa), Min: p1 (hPa), Max: p1 (hPa), Min: p2 (hPa), Max: p2 (hPa)'
        
        temperature_keys = ['Tref (°C)', 't1 (°C)', 't2 (°C)']
        rh_keys = ['RHref (%RH)', 'RH1% (%)', 'RH2% (%)']
        pressure_keys = ['p1 (hPa)', 'p2 (hPa)']
    else:
        temperature_header = 'Rank, Interval start (s), Interval end (s), Slope: Tref (°C), Slope: t1 (°C), Mean: Tref (°C), Mean: t1 (°C), Min: Tref (°C), Max: Tref (°C), Min: t1 (°C), Max: t1 (°C)'
        rh_header = 'Rank, Interval start (s), Interval end (s), Slope: RHref (%RH), Slope: RH1% (%), Mean: RHref (%RH), Mean: RH1% (%), Min: RHref (%RH), Max: RHref (%RH), Min: RH1% (%), Max: RH1% (%)'
        pressure_header = 'Rank, Interval start (s), Interval end (s), Slope: p1 (hPa), Mean: p1 (hPa), Min: p1 (hPa), Max: p1 (hPa)'
        
        temperature_keys = ['Tref (°C)', 't1 (°C)']
        rh_keys = ['RHref (%RH)', 'RH1% (%)']
        pressure_keys = ['p1 (hPa)']

    # Sort and save results
    df_temp = sort_and_save_results(results, f'{analysis_path}/temperature_analysis.csv', temperature_keys, temperature_header)
    df_rh = sort_and_save_results(results, f'{analysis_path}/rh_analysis.csv', rh_keys, rh_header)
    df_pressure = sort_and_save_results(results, f'{analysis_path}/pressure_analysis.csv', pressure_keys, pressure_header)
    
    df_results = pd.DataFrame(results)

    # Add ranks based on slope categories
    df_results = df_results.merge(df_temp[['Interval start (s)', 'Rank']], on='Interval start (s)').rename(columns={'Rank': 'Temp Rank'})
    df_results = df_results.merge(df_rh[['Interval start (s)', 'Rank']], on='Interval start (s)').rename(columns={'Rank': 'RH Rank'})
    df_results = df_results.merge(df_pressure[['Interval start (s)', 'Rank']], on='Interval start (s)').rename(columns={'Rank': 'Pressure Rank'})

    # Plot and save graphs
    plot_and_save_graphs(df, analysis_path, has_sensor2)
    plot_slope_graphs(df_results, analysis_path, has_sensor2)

if __name__ == '__main__':
    main()
