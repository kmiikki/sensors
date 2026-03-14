# DPS Logger

DPS Logger is a command-line toolset for communicating with DPS RS-485 pressure sensors and recording measurement data.

The system provides utilities for:

- scanning sensor addresses
- reading pressure values
- interactive serial communication
- logging measurements to CSV
- generating plots and statistics from recorded data

The tools are designed for Linux systems and communicate with sensors using a simple ASCII protocol over RS-485 (9600 8N1).

---

## Installation

Run the installer as root:

```bash
sudo ./install.sh
````

This installs the application to:

```
/opt/dpslogger
```

and creates command wrappers in:

```
/usr/local/bin
```

---

## Available commands

| Command           | Description                                   |
| ----------------- | --------------------------------------------- |
| `dps-logger`      | Record pressure measurements to CSV           |
| `dps-term`        | Interactive terminal for sensor communication |
| `dps-scan`        | Scan RS-485 bus for sensor addresses          |
| `dps-read`        | Read pressure from a sensor                   |
| `dps-set-address` | Change sensor address                         |
| `dps-plot`        | Generate plots and statistics from a CSV file |

---

## Example workflow

Typical workflow:

```bash
dps-port-check
dps-scan
dps-read --addr 1
dps-logger --addr 1
dps-plot dps_addr01_YYYYMMDD-HHMMSS.csv
```

Detailed usage instructions are available in the Quick Start guide.

---

## Documentation

Additional documentation is available in the `docs/` directory:

* Quick start: `docs/QUICK_START.md`
* Command reference: `docs/CLI_REFERENCE.md`
* RS-485 protocol: `docs/RS485_PROTOCOL.md`

---

## Directory structure

```
dpslogger/
    cli/        Command-line tools
    tools/      Setup and diagnostic utilities
    simulator/  Placeholder for future simulator support
```

Example output files are provided in:

```
examples/
```

---

## Notes

* DPS Logger is installed as a shared read-only application.
* Measurement data should be written to user-owned directories.
* Only one process should normally access a serial device at a time.

---

## Uninstall

To remove the installation:

```bash
sudo ./uninstall.sh
```

---

## Author

Kim Miikki

## Copyright

Copyright (c) 2026 Kim Miikki

---

## License

This project is licensed under the MIT License.

