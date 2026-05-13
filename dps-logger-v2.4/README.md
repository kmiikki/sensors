# DPSlogger v2.4

Part of the **sensors** repository.

DPSlogger v2.4 is a command-line toolset for DPS8000 / RS-485 pressure sensors. It supports sensor commissioning, address and unit management, bus debugging, automatic multi-sensor profiling, measurement logging, summary CSV generation, and plotting.

The project is intended for laboratory use with DPS8000 pressure sensors connected through an RS-485 bus and a USB-to-RS485 adapter.

Communication uses an ASCII protocol over RS-485, typically at 9600 baud.

---

## Features

- Scan an RS-485 bus for connected sensors
- Read pressure values from individual sensors
- Change sensor addresses and pressure units
- Disable or quiet sensor autoread before scanning, address changes, interactive debugging, or logging
- Use an interactive serial terminal for manual commands
- Profile multi-sensor burst timing automatically
- Probe and verify unit mappings for DPS8000 sensors
- Generate `dps_config.json` from a profiling run
- Reuse `dps_config.json` from the current directory, parent directory, or grandparent directory
- Log measurements from one or more sensors to per-sensor detail CSV files
- Generate a researcher-friendly summary CSV with logical sensor IDs such as `p1`, `p2`, `p3`, and `p4`
- Generate per-sensor plots, histograms, regression diagnostics, statistics, and combined summary plots
- Use low-level serial debugging tools when troubleshooting communication problems

---

## Installation

Run the installer as root.

For the Raspberry Pi lab314 environment:

```bash
sudo ./install.sh --python /opt/lab314/bin/python
````

Generic installation:

```bash
sudo ./install.sh
```

The installer places the software in:

```text
/opt/dpslogger
```

and installs command wrappers in:

```text
/usr/local/bin
```

Installed command wrappers:

```text
dps-logger
dps-bus-logger
dps-read
dps-scan
dps-set-address
dps-unit
dps-autoread-off
dps-term
dps-plot
dps-port-check
dps-loopback-test
dps-setup-udev
dps-serial-debug
dps-profile-cycle
dps-profile-to-config
```

---

## Serial Port

By default DPSlogger expects the serial device to be available as:

```text
/dev/ttyLOG
```

This stable name can be created using the provided udev setup tool:

```bash
sudo dps-setup-udev
```

If no udev rule is installed, the sensor may appear as a standard device such as:

```text
/dev/ttyUSB0
/dev/ttyACM0
```

In that case specify the port manually:

```bash
dps-read --port /dev/ttyUSB0 --addr 1
```

Users may need to be added to the appropriate serial device group:

```bash
sudo usermod -aG dialout <username>
```

After changing group membership, the user must log out and log back in.

---

## Configuration

DPSlogger v2.4 uses `dps_config.json` for multi-sensor bus configuration.

The logger searches for the configuration file in this order:

```text
1. --config FILE
2. ./dps_config.json
3. ../dps_config.json
4. ../../dps_config.json
```

Resolution policy:

```text
first match wins
no merge
no inheritance
no incremental fallback
```

This means the first found `dps_config.json` is used as the complete configuration.

A useful workflow is to place `dps_config.json` in a parent directory when the same sensor bus, addresses, and physical setup are reused for multiple measurement directories.

---

## Automatic Profiling

If `dps_config.json` is not found, `dps-logger` can automatically run the profiling workflow:

```text
dps-profile-cycle
→ dps-profile-to-config
→ dps_config.json
→ measurement logging
```

The profiling workflow can:

* probe active sensor addresses
* verify DPS8000 unit codes
* restore the original unit after probing
* measure burst reply timing
* recommend collection timeout and cycle interval values
* generate `dps_config.json`

The verified DPS8000 unit mapping used by the v2.4 workflow is:

```text
0 = mbar
1 = Pa
2 = kPa
3 = MPa
4 = hPa
5 = bar
```

Some DPS8000 unit set commands may not return a normal reply. In that case, the command is accepted if a follow-up `U,?` query reports the requested unit code.

---

## Measurement Data

`/opt/dpslogger` is used only for the installed application.

Measurement data, plots, statistics, metadata, and output files are written to:

* the current working directory
* or a user-specified output directory

The installation directory itself is not used for storing measurement results.

A typical v2.4 multi-sensor run creates files like:

```text
dps_addr01_20260511-163435.csv
dps_addr02_20260511-163435.csv
dps_addr03_20260511-163435.csv
dps_addr04_20260511-163435.csv
dps_summary_20260511-163435.csv
dps_run_20260511-163435.json
```

The per-sensor detail CSV files use address-based names:

```text
dps_addrNN_<session>.csv
```

The summary CSV uses logical sensor IDs:

```text
ts_iso,timestamp,time,cycle,p1,p2,p3,p4
```

---

## CSV Formats

Per-sensor detail CSV:

```csv
ts_iso,timestamp,time,cycle,addr,pressure,unit,latency_s,source,status
```

Summary CSV:

```csv
ts_iso,timestamp,time,cycle,p1,p2,p3,p4
```

The detail CSV is intended for technical and diagnostic use.

The summary CSV is intended for researchers and downstream analysis.

---

## Commands

### dps-logger

Main measurement logger command. This is the recommended command for normal logging.

Example with explicit first-run sensor selection:

```bash
dps-logger --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4 --interval 5 --duration 60
```

Later, when `dps_config.json` exists in the current directory, parent directory, or grandparent directory:

```bash
dps-logger --duration 60
```

Useful options:

```text
--addresses 1,2,3,4
--ids p1,p2,p3,p4
--interval 5
--duration 60
--config dps_config.json
--profile-only
--reprofile
--quiet
--pretty
--verbose
```

### dps-bus-logger

Alias/wrapper for the same bus logger implementation used by `dps-logger`.

### dps-profile-cycle

Profile DPS8000 RS-485 burst timing and unit behavior.

Example:

```bash
dps-profile-cycle --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4
```

### dps-profile-to-config

Convert a profile JSON file into `dps_config.json`.

Example:

```bash
dps-profile-to-config dps_profile_20260513-115919.json
```

### dps-read

Read a single pressure value from a sensor.

Example:

```bash
dps-read --addr 1
```

### dps-scan

Scan the RS-485 bus for connected sensors.

Example:

```bash
dps-scan
```

### dps-set-address

Change the address of a sensor.

Example:

```bash
dps-set-address --from 1 --to 2
```

### dps-unit

Read or change the pressure unit used by a sensor.

Examples:

```bash
dps-unit --addr 1
dps-unit --addr 1 --unit 2
```

### dps-autoread-off

Send a best-effort autoread-off sequence before scanning, address changes, interactive debugging, or logging.

This is useful when a sensor is continuously transmitting and manual terminal debugging becomes difficult.

Typical use:

```bash
dps-autoread-off
```

Example with explicit serial port and limited address range:

```bash
dps-autoread-off --port /dev/ttyUSB0 --start 0 --end 4
```

### dps-term

Interactive terminal for direct communication with the sensor.

Example:

```bash
dps-term
```

### dps-plot

Generate plots and statistics from DPSlogger CSV files.

Plot the latest run:

```bash
dps-plot --latest --all
```

Plot the latest run in black-and-white mode:

```bash
dps-plot --latest --all --bw
```

Plot a specific session:

```bash
dps-plot --session 20260511-163435 --all
```

Plot only the combined summary figure:

```bash
dps-plot dps_summary_20260511-163435.csv --combined
```

Plot one detail CSV:

```bash
dps-plot dps_addr01_20260511-163435.csv
```

Useful v2.4 plot options:

```text
--summary
--per-sensor
--combined
--all
--latest
--last
--session SESSION
--dir DIR
--out-dir DIR
--time auto|s|min|h|d
--bw
--bins N
--fine-hist
--combined-markers
--no-markers
```

### dps-port-check

Check that the selected serial port exists and is accessible.

Example:

```bash
dps-port-check
```

### dps-loopback-test

Perform a serial loopback test for debugging adapter and cable problems.

### dps-setup-udev

Install a udev rule that creates a stable serial device name such as `/dev/ttyLOG`.

Example:

```bash
sudo dps-setup-udev
```

### dps-serial-debug

Low-level serial debugging utility for testing baud rate, line endings, addresses, and raw communication.

Typical example:

```bash
dps-serial-debug --interactive /dev/ttyUSB0
```

---

## Typical Workflow

1. Check that the serial port exists:

```bash
dps-port-check
```

2. If the bus is noisy because a sensor may still be in autoread mode, quiet the bus first:

```bash
dps-autoread-off
```

3. Scan the RS-485 bus:

```bash
dps-scan
```

4. Read a pressure value from a sensor:

```bash
dps-read --addr 1
```

5. Change the pressure unit if needed:

```bash
dps-unit --addr 1 --unit 2
```

6. Change sensor addresses if necessary:

```bash
dps-set-address --from 1 --to 2
```

7. Run a multi-sensor logger workflow. On the first run, allow profiling/config generation:

```bash
dps-logger --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4 --interval 5 --duration 60
```

8. Later, when `dps_config.json` exists in the current directory, parent directory, or grandparent directory:

```bash
dps-logger --duration 60
```

9. Generate plots:

```bash
dps-plot --latest --all
```

---

## Plot Outputs

A multi-sensor v2.4 plotting run can generate:

```text
dps_addr01_plot_<session>.png
dps_addr02_plot_<session>.png
dps_addr03_plot_<session>.png
dps_addr04_plot_<session>.png
dps_summary_plot_<session>.png
```

Additional per-sensor diagnostics may include:

```text
dps_addr01_<session>_hist.png
dps_addr01_<session>_regression.png
dps_addr01_<session>_stats.txt
```

The histogram and regression files are diagnostic outputs.

The main researcher-facing plots are:

```text
per-sensor pressure-vs-time plots
combined summary plot
```

---

## Examples

Example measurement data is available in:

```text
../examples/
```

A complete four-sensor example run is provided in:

```text
../examples/four-sensor-run-20260511-163435/
```

The example can be used to test plotting without connected hardware:

```bash
cd ../examples/four-sensor-run-20260511-163435
dps-plot --dir . --session 20260511-163435 --all
```

---

## Documentation

Additional documentation is available in the `docs/` directory:

```text
docs/QUICK_START.md
docs/CLI_REFERENCE.md
docs/RS485_PROTOCOL.md
```

---

## Project Structure

```text
.
├── install.sh
├── uninstall.sh
├── VERSION
├── README.md
├── docs/
│   ├── CLI_REFERENCE.md
│   ├── QUICK_START.md
│   └── RS485_PROTOCOL.md
└── dpslogger/
    ├── __init__.py
    ├── adapter.py
    ├── csv_writer.py
    ├── dps_autoread_off.py
    ├── profiles.py
    ├── protocol.py
    ├── transport.py
    ├── cli/
    │   ├── __init__.py
    │   ├── common.py
    │   ├── dps_address_scan.py
    │   ├── dps_bus_logger.py
    │   ├── dps_plot.py
    │   ├── dps_profile_cycle.py
    │   ├── dps_profile_to_config.py
    │   ├── dps_read.py
    │   ├── dps_set_address.py
    │   ├── dps_term.py
    │   └── dps_unit.py
    └── tools/
        ├── __init__.py
        ├── README.md
        ├── dps-serial-debug
        ├── loopback_test.py
        ├── port_check.py
        └── setup_udev.py
```

---

## Uninstall

To remove the installation:

```bash
sudo ./uninstall.sh
```

This removes:

* `/opt/dpslogger`
* installed wrappers in `/usr/local/bin`

User-created measurement files are not removed.

---

## Notes

* DPSlogger is installed as a shared read-only application.
* `/opt/dpslogger` is reserved for the installed application.
* Measurement data should always be written to a user-owned directory.
* The tools do not implement a serial port lock.
* Only one process should normally access a serial device at a time.
* Concurrent access is intended only for debugging.

---

## License

This project is part of the **sensors** repository and is licensed under the MIT License.

See the repository root `LICENSE` file for details.

---

## Author

Kim Miikki

Copyright (c) 2026 Kim Miikki
