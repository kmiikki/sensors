# DPSlogger v2.4 Command Reference

This document summarizes the command-line tools included in DPSlogger v2.4.

All commands support `--help` for detailed usage.

---

## Common defaults

| Setting | Default |
|---|---|
| Serial port | `/dev/ttyLOG` |
| Baudrate | `9600` |
| EOL | `cr` |
| Command prefix | one leading space |
| Read command | `G` for v2.4 burst profiling/logging defaults |
| Config name | `dps_config.json` |
| Output directory | current directory |
| Filename prefix | `dps` |

---

## Configuration search

`dps-logger` searches for `dps_config.json` in this order:

```text
1. --config FILE
2. ./dps_config.json
3. ../dps_config.json
4. ../../dps_config.json
```

Policy:

```text
first match wins
no merge
no inheritance
no incremental fallback
```

The first found `dps_config.json` is used as the complete configuration.

---

## dps-logger

Main measurement logger command.

`dps-logger` is the recommended command for normal logging. It uses the same bus logger implementation as `dps-bus-logger`.

First run with explicit active sensors:

```bash
dps-logger --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4 --interval 5 --duration 60
```

Later run when `dps_config.json` exists:

```bash
dps-logger --duration 60
```

Useful options:

```text
--config FILE
--port DEVICE
--addresses 1,2,3,4
--ids p1,p2,p3,p4
--addr 1
--interval SECONDS
--duration SECONDS
--read-mode serial|burst
--read-command G|R|*G|*R
--collect-timeout SECONDS
--command-gap SECONDS
--profile-only
--reprofile
--auto-profile
--no-auto-profile
--summary
--no-summary
--pretty
--verbose
--quiet
```

Typical output files:

```text
dps_addr01_<session>.csv
dps_addr02_<session>.csv
dps_summary_<session>.csv
dps_run_<session>.json
```

---

## dps-bus-logger

Alias/wrapper for the same bus logger implementation used by `dps-logger`.

Example:

```bash
dps-bus-logger --addresses 1,2,3,4 --ids p1,p2,p3,p4 --duration 60
```

---

## dps-profile-cycle

Profile DPS8000 RS-485 burst timing and unit behavior.

Example:

```bash
dps-profile-cycle --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4
```

Common options:

```text
--port DEVICE
--baudrate 9600
--timeout SECONDS
--eol cr|lf|crlf|none
--command-prefix " "
--addresses 1,2,3,4
--ids p1,p2,p3,p4
--rounds N
--read-command G|R
--command-gap SECONDS
--collect-timeout SECONDS
--probe-units
--no-probe-units
```

Output:

```text
dps_profile_<session>.json
```

The profile JSON is an audit trail and commissioning measurement. It can be converted into `dps_config.json` with `dps-profile-to-config`.

---

## dps-profile-to-config

Convert a profile JSON file into `dps_config.json`.

Example:

```bash
dps-profile-to-config dps_profile_20260513-115919.json
```

Typical output:

```text
dps_config.json
```

The generated config includes transport settings, readout settings, unit mapping, sensor IDs, addresses, unit verification metadata, and timing recommendations.

---

## dps-scan

Scan the RS-485 bus for connected sensors.

Example:

```bash
dps-scan
```

With explicit port:

```bash
dps-scan --port /dev/ttyUSB0
```

Use `dps-autoread-off` first if the bus is noisy because a sensor is continuously transmitting.

---

## dps-read

Read a single pressure value from a sensor.

Example:

```bash
dps-read --addr 1
```

With explicit port:

```bash
dps-read --port /dev/ttyUSB0 --addr 1
```

---

## dps-set-address

Change the RS-485 address of a sensor.

Example:

```bash
dps-set-address --from 1 --to 2
```

Use this when multiple sensors share a bus and unique addresses are required.

---

## dps-unit

Read or change the pressure unit used by a sensor.

Examples:

```bash
dps-unit --addr 1
dps-unit --addr 1 --unit 2
```

Verified DPS8000 unit codes for this project:

```text
0 = mbar
1 = Pa
2 = kPa
3 = MPa
4 = hPa
5 = bar
```

---

## dps-autoread-off

Send a best-effort autoread-off sequence.

This is useful before scanning, address changes, interactive terminal work, or debugging when a sensor is continuously transmitting and manual commands are hard to type.

Typical use:

```bash
dps-autoread-off
```

Explicit port and limited address range:

```bash
dps-autoread-off --port /dev/ttyUSB0 --start 0 --end 4
```

---

## dps-term

Interactive terminal for direct communication with a sensor.

Example:

```bash
dps-term
```

Use this for manual commands and raw response inspection.

---

## dps-plot

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

Important options:

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

Output examples:

```text
dps_addr01_plot_<session>.png
dps_addr02_plot_<session>.png
dps_summary_plot_<session>.png
dps_addr01_<session>_hist.png
dps_addr01_<session>_regression.png
dps_addr01_<session>_stats.txt
```

The combined summary plot uses logical IDs such as `p1`, `p2`, `p3`, and `p4`.

By default, combined summary plots do not use markers. Use `--combined-markers` to enable markers for combined plots.

Use `--bins N` when a specific histogram bin count is required. Explicit `--bins N` overrides automatic histogram bin selection.

---

## dps-port-check

Check that the selected serial port exists and is accessible.

Example:

```bash
dps-port-check
```

---

## dps-loopback-test

Perform a serial loopback test for debugging adapter and cable problems.

Example:

```bash
dps-loopback-test
```

---

## dps-setup-udev

Install a udev rule that creates a stable serial device name such as `/dev/ttyLOG`.

Example:

```bash
sudo dps-setup-udev
```

---

## dps-serial-debug

Low-level serial debugging utility for testing baud rate, line endings, addresses, and raw communication.

Example:

```bash
dps-serial-debug --interactive /dev/ttyUSB0
```

---

## Recommended command sequence

Typical commissioning and measurement workflow:

```bash
dps-port-check
dps-autoread-off
dps-scan
dps-read --addr 1
dps-logger --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4 --interval 5 --duration 60
dps-plot --latest --all
```

Later runs, when `dps_config.json` already exists:

```bash
dps-logger --duration 60
dps-plot --latest --all
```
