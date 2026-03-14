# DPS Logger v2

Part of the **sensors** repository.

## Overview

DPS Logger is a command-line toolset for communicating with DPS RS-485 pressure sensors and recording measurement data.

The tools support:

- scanning sensors on an RS-485 bus
- reading pressure values
- interactive serial communication
- logging measurements to CSV files
- generating plots and statistics from recorded data

Communication uses a simple ASCII protocol over RS-485 (9600 8N1).

---

## Table of Contents

- [Installation](#installation)
- [Serial port](#serial-port)
- [Commands](#commands)
- [Typical workflow](#typical-workflow)
- [Documentation](#documentation)
- [Project structure](#project-structure)
- [Uninstall](#uninstall)
- [License](#license)
- [Author](#author)

---

# Installation

Run the installer as root:

```bash
sudo ./install.sh
````

The installer places the software in:

```
/opt/dpslogger
```

and installs command wrappers in:

```
/usr/local/bin
```

---

## Serial port

By default DPS Logger expects the serial device to be available as:

```
/dev/ttyLOG
````

This name can be created using the provided udev setup tool:

```bash
sudo dps-setup-udev
````

If no udev rule is installed, the sensor may appear as a standard device such as:

```
/dev/ttyUSB0
/dev/ttyACM0
```

In that case specify the port manually:

```bash
dps-read --port /dev/ttyUSB0 --addr 1
```
---

# Commands

The following command-line tools are installed.

### dps-logger

Record pressure measurements from a sensor and write them to a CSV file.

### dps-read

Read a single pressure value from a sensor.

### dps-scan

Scan the RS-485 bus for connected sensors.

### dps-set-address

Change the address of a sensor.

### dps-term

Interactive terminal for direct communication with the sensor.

### dps-plot

Generate plots and statistics from a CSV measurement file.

Detailed command documentation is available in:

```
docs/CLI_REFERENCE.md
```

---

# Typical workflow

A typical measurement workflow:

1. Check the serial port:

```bash
dps-port-check
```

2. Scan the RS-485 bus:

```bash
dps-scan
```

3. Read a pressure value:

```bash
dps-read --addr 1
```

4. Record measurements:

```bash
dps-logger --addr 1
```

5. Generate plots:

```bash
dps-plot dps_addr01_YYYYMMDD-HHMMSS.csv
```

Example output files can be found in the `examples/` directory.

---

## Documentation

Additional documentation is available in the `docs/` directory:

- Quick start guide: `docs/QUICK_START.md`
- Command reference: `docs/CLI_REFERENCE.md`
- RS-485 protocol description: `docs/RS485_PROTOCOL.md`

---

# Project structure

```
dpslogger/
    cli/        Command-line tools
    tools/      Setup and diagnostic utilities
    simulator/  Placeholder for simulator support
```

---

# Uninstall

To remove the installation:

```bash
sudo ./uninstall.sh
```

---

# License

This project is part of the **sensors** repository and is licensed under the MIT License.

See the repository root `LICENSE` file for details.

---

# Author

Kim Miikki

Copyright (c) 2026 Kim Miikki

