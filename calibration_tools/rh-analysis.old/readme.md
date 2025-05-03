# RH Analysis CSV Processing

## Overview
`rh_analysis.py` is a script designed to process relative humidity (RH) data from `rh_analysis.csv`, filtering, analyzing, and generating calibration input files for the [THP Calibration Program](https://github.com/kmiikki/sensors/tree/main/thpcal). The script is part of a pipeline managed by `thp-process.py`, which automates THP data conversion, merging, calibration, and analysis.

## Directory Structure
```
.
└── cal
    └── analysis
        └── rh_analysis.csv
```
`rh_analysis.csv` can be found at any of these levels, with selection preference from top to bottom in the tree.

## Input Data Format
The script processes a CSV file (`rh_analysis.csv`) that contains relative humidity analysis results with the following columns:
```
Rank,Interval start (s),Interval end (s),Sum of abs(slope),Slope: RHref (%RH),Slope: RH1% (%),Slope: RH2% (%),
Mean: RHref (%RH),Mean: RH1% (%),Mean: RH2% (%),Min: RHref (%RH),Max: RHref (%RH),Min: RH1% (%),Max: RH1% (%),Min: RH2% (%),Max: RH2% (%)
```

## Processing Steps
1. **File Location Detection:** The script searches for `rh_analysis.csv` in predefined directories.
2. **Data Filtering:** Removes rows where `Sum of abs(slope)` exceeds a threshold (default: 0.003).
3. **Calibration Level Extraction:** Identifies RH values closest to every tenth RH level (0-100%) while avoiding duplicate ranks.
4. **Output Generation:** Produces CSV and text files with extracted calibration values:
   - `rh1-ranks.txt` (RH1% calibration data)
   - `rh2-ranks.txt` (RH2% calibration data)
5. **Visualization:** Generates plots (`.png`) displaying calibration levels.

## Output Format
Example output files:

**rh1-ranks.txt**
```
RHref%,RH1%
2.742791,6.311833
29.236447,31.597167
39.015465,39.9585
79.377179,72.744667
```

**rh2-ranks.txt**
```
RHref%,RH2%
2.631116,4.673333
9.471732,12.364833
29.236447,30.611667
39.015465,39.398167
81.155793,79.810333
```

## Usage
### Running the Script
Ensure `rh_analysis.py` is located in `/opt/tools` (or within your `env path`) and execute it from the same working directory as `thp-process.py`.

```sh
python3 rh_analysis.py /path/to/rh_analysis.csv -th 0.003
```
- `-th` (optional): Threshold value for filtering `Sum of abs(slope)`.

### Example Execution
```sh
python3 rh_analysis.py cal/analysis/rh_analysis.csv -th 0.002
```

## Dependencies
- Python 3
- `pandas`
- `matplotlib`
- `argparse`

## License
This project is licensed under the MIT License. See `LICENSE` for details.

