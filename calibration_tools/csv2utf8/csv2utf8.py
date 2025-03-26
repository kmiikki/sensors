#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar 17 12:44:57 2025

@author: Kim
"""

import os
import subprocess

def get_file_encoding(file_path):
    result = subprocess.run(['file', '-bi', file_path], capture_output=True, text=True)
    mime_type = result.stdout.strip()
    charset_prefix = 'charset='
    if charset_prefix in mime_type:
        encoding = mime_type.split(charset_prefix)[-1]
        return encoding.lower()
    return None

def convert_to_utf8(file_path, output_dir):
    with open(file_path, 'r', encoding='iso-8859-1') as file:
        content = file.read()

    output_path = os.path.join(output_dir, os.path.basename(file_path))
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    # Define the utf-8 sub directory
    utf8_dir = 'utf-8'

    # Get the current directory
    current_dir = os.getcwd()

    # Get the list of txt and csv files in current directory
    files = [f for f in os.listdir(current_dir) if f.endswith('.txt') or f.endswith('.csv')]

    is_found = False
    for file in files:
        file_path = os.path.join(current_dir, file)
        encoding = get_file_encoding(file_path)

        if encoding == 'iso-8859-1':
            if not is_found:
                # Create the utf-8 directory if it doesn't exist
                if not os.path.exists(utf8_dir):
                    os.makedirs(utf8_dir)
                id_found = True
            convert_to_utf8(file_path, utf8_dir)
            print(f"Converted {file} to UTF-8")

if __name__ == "__main__":
    main()
