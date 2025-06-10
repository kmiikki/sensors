#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jun  9 14:35:23 2025

@author: Kim Miikki
"""

#!/usr/bin/env python3
import sys
import os

def fix_file(src, dest):
    with open(src, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    if not lines:
        print("File is empty.")
        return

    header = lines[0].strip()
    header_fields = [h.strip() for h in header.split(',')]
    fields = len(header_fields)
    
    fixed_lines = [header + '\n']
    fixed_count = 0

    for line in lines[1:]:
        lstripped = line.lstrip()
        if lstripped.count(',') >= fields:
            fixed_lines.append(lstripped.replace(', ',''))
            fixed_count += 1

    if fixed_count >0:
        with open(dest, 'w', encoding='utf-8') as f:
            f.writelines(fixed_lines)   
        print(f"Processed '{src}'. Fixed {fixed_count} garbled lines. Wrote output to '{dest}'.")
    else:
        print("Nothing to fix.")

def main():
    if len(sys.argv) < 2:
        in_file = 'thp.csv'
    else:
        in_file = sys.argv[1]
    if not os.path.exists(in_file):
        print(f"File '{in_file}' does not exist.")
        return

    stem, ext = os.path.splitext(os.path.basename(in_file))
    out_file = f"{stem}.fixed.csv"
    fix_file(in_file, out_file)

if __name__ == '__main__':
    main()
