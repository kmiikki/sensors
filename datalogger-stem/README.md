# datalogger-stem

**Minimal, sensor-agnostic datalogger skeleton in Python.**

This directory provides a reusable, hardware-independent base for building
custom dataloggers. It defines a robust timing and logging framework but
contains no sensor-specific code — only a demonstration that records the
current UNIX time (`time.time()`).

---

## Overview

| File | Purpose |
|------|----------|
| `datalogger-stem.py` | Main datalogger loop (CLI, interval timing, error handling) |
| `logfile.py` | Reusable logging classes: `DataLog` and `ErrorLog` |
| `README.md` | Documentation (this file) |

The code can be used as a starting point for any data acquisition system
(e.g., temperature, humidity, camera-based, or pressure loggers).

---

## Features

- Clean scheduling using `perf_counter` to minimize long-term drift  
- Graceful shutdown on `Ctrl+C` (finishes current cycle before stopping)  
- CSV-style measurement logging via `DataLog`  
- Human-readable error logging via `ErrorLog`  
- Platform-agnostic (Linux / Windows / Raspberry Pi)  
- No sensor dependencies — plug in your own `read_once()` implementation  

---

## Usage

Run the skeleton directly to test basic functionality:

```bash
python datalogger-stem.py --interval 1.0 --base-dir data --prefix test
````

This creates a time-stamped directory such as:

```
data/20251022-132045/
 ├── test.csv
 └── 20251022-132045-error.log
```

Each line in `test.csv` contains the current UNIX time in seconds (float).

---

## Example: Add a Real Sensor

To adapt the stem for real measurements, modify the `read_once()` function
in `datalogger-stem.py`:

```python
def read_once() -> list[float]:
    # Example for a temperature and humidity sensor
    temperature = sensor.read_temperature()
    humidity = sensor.read_humidity()
    return [time.time(), temperature, humidity]
```

You can also extend the header row accordingly:

```python
data_log.write(["timestamp", "temperature_C", "humidity_%"])
```

---

## Error Handling

All caught exceptions during measurement are appended to an error log:

```
2025-10-22 13:20:01.123456, 42, sensor read timeout
```

This allows long unattended runs without losing main data continuity.

---

## Suggested Directory Structure

If your repository contains multiple sensor loggers:

```
sensors/
├── datalogger-stem/
│   ├── logfile.py
│   ├── datalogger-stem.py
│   └── README.md
├── pressure-logger/
├── temperature-logger/
└── camera-logger/
```

Each specialized logger can import and reuse `DataLog` and `ErrorLog` from
`datalogger-stem`.

---

## Quick Start

You can test the logger immediately after cloning the repository.

### 1️⃣ Clone the repository

```bash
git clone https://github.com/kmiikki/sensors.git
cd sensors/datalogger-stem
```

### 2️⃣ Run the logger

```bash
python datalogger-stem.py --interval 1.0 --base-dir data --prefix test
```

The program creates a new time-stamped subdirectory inside `data/`,
writes measurement lines every second, and prints them on the terminal.

Example output:

```
1730001234.456
1730001235.457
1730001236.458
Stopped. Total rows written: 3
```

Directory structure:

```
data/20251022-132045/
 ├── test.csv
 └── 20251022-132045-error.log
```

### 3️⃣ Stop the logger

Press **Ctrl + C** to stop safely.
The current cycle will finish before the program exits.

---

### Optional parameters

| Option          | Description                      | Default |
| --------------- | -------------------------------- | ------- |
| `--interval`    | Measurement interval in seconds  | `1.0`   |
| `--base-dir`    | Base directory for logs          | `data`  |
| `--prefix`      | File prefix for data log         | `data`  |
| `--csv-sep`     | CSV separator for data log       | `,`     |
| `--err-csv-sep` | CSV separator for error log      | `, `    |
| `--decimals`    | Decimal places in numeric output | `3`     |

---

### 4️⃣ Add your sensor

Edit `read_once()` in `datalogger-stem.py`:

```python
def read_once() -> list[float]:
    temperature = sensor.read_temperature()
    humidity = sensor.read_humidity()
    return [time.time(), temperature, humidity]
```

Then update the header:

```python
data_log.write(["timestamp", "temperature_C", "humidity_%"])
```

Run again — you now have a fully working custom datalogger.

---

## License

MIT License © 2025 Kim Miikki<br>
Aalto University, School of Chemical Engineering
