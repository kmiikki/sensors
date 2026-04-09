# DPS Logger v2

Part of the **sensors** repository.

DPS Logger v2 is a command-line toolset for communicating with DPS RS-485 pressure sensors, configuring sensors, recovering from communication problems, recording measurements, and generating plots and statistics from the recorded data.

The project is intended for laboratory use with DPS pressure sensors connected through an RS-485 bus and a USB-to-RS485 adapter.

Communication uses a simple ASCII protocol over RS-485 (9600 8N1).

---

## Features

* Scan an RS-485 bus for connected sensors
* Read pressure values from individual sensors
* Change sensor addresses and pressure units
* Disable or quiet sensor autoread before scanning, address changes, or logging
* Use an interactive serial terminal for manual commands
* Log measurements from one or more sensors to CSV files
* Generate plots and statistics from recorded CSV files
* Use low-level serial debugging tools when troubleshooting communication problems

---

## Installation

Run the installer as root:

```bash
sudo ./install.sh
````

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
```

---

## Measurement Data

`/opt/dpslogger` is used only for the installed application.

Measurement data, plots, statistics, metadata, and output files are written to:

* the current working directory
* or a user-specified output directory

The installation directory itself is not used for storing measurement results.

Example output files:

```text
dps_addr01_20260408-122238.csv
dps_addr01_pressure.png
dps_addr01_hist.png
dps_addr01_regression.png
dps_addr01_stats.txt
dps_run.json
```

---

## Serial Port

By default DPS Logger expects the serial device to be available as:

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

---

## Commands

### dps-logger

Main measurement logger command. This is an alias for `dps-bus-logger`.

### dps-bus-logger

Record measurements from one or more sensors and write the results to CSV files.

Typical example:

```bash
dps-bus-logger --addr 1
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

Example:

```bash
dps-unit --addr 1
dps-unit --addr 1 --unit 1
```

### dps-autoread-off

Send a best-effort autoread-off sequence before scanning, address changes, interactive debugging, or logging.

The tool first tries the direct-mode command form:

```text
A,9999
```

and then sweeps the selected RS-485 address range using:

```text
<addr>:A,9999
```

This is useful when a sensor is continuously transmitting because autoread is still enabled.

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

Generate plots and statistics from a recorded CSV measurement file.

Example:

```bash
dps-plot dps_addr01_20260408-122238.csv
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
dps-unit --addr 1
```

6. Change the sensor address if necessary:

```bash
dps-set-address --from 1 --to 2
```

7. Record measurements:

```bash
dps-logger --addr 1
```

8. Generate plots and statistics:

```bash
dps-plot dps_addr01_YYYYMMDD-HHMMSS.csv
```

---

## Documentation

Additional documentation is available in the `docs/` directory:

* `docs/QUICK_START.md`
* `docs/CLI_REFERENCE.md`
* `docs/RS485_PROTOCOL.md`

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
    │   ├── dps_bus_logger.py
    │   ├── dps_read.py
    │   ├── dps_address_scan.py
    │   ├── dps_set_address.py
    │   ├── dps_unit.py
    │   ├── dps_term.py
    │   └── dps_plot.py
    ├── tools/
    │   ├── dps-serial-debug
    │   ├── loopback_test.py
    │   ├── port_check.py
    │   └── setup_udev.py
    └── simulator/
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

* DPS Logger is installed as a shared read-only application.
* `/opt/dpslogger` is reserved for the installed application.
* Measurement data should always be written to a user-owned directory.
* The tools do not implement a serial port lock.
* Only one process should normally access a serial device at a time.
* Concurrent access is intended only for debugging.

Users may need to be added to the appropriate serial device group:

```bash
sudo usermod -aG dialout <username>
```

After changing group membership, the user must log out and log back in.

---

## License

This project is part of the **sensors** repository and is licensed under the MIT License.

See the repository root `LICENSE` file for details.

---

## Author

Kim Miikki

Copyright (c) 2026 Kim Miikki

