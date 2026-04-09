# DPS Logger v2

DPS Logger v2 is a Python-based toolkit for communicating with Druck / GE DPS8000 pressure sensors over RS-485.

The project includes:

- pressure sensor communication
- bus scanning and address management
- pressure logging to CSV
- plotting and statistical analysis
- installation and uninstall scripts
- helper tools for serial debugging and udev setup

The package is intended for Linux systems such as Raspberry Pi and Ubuntu.

---

## Repository layout

```text
dps-logger-v2/
├── dpslogger-package/
│   ├── docs/
│   ├── dpslogger/
│   ├── README.md
│   ├── VERSION
│   ├── install.sh
│   └── uninstall.sh
├── examples/
└── README.md
````

* `dpslogger-package/` contains the installable package.
* `examples/` contains reference measurement data and generated plots.

---

## Install

```bash
cd dpslogger-package
sudo ./install.sh --python /path/to/python3
```

Example:

```bash
sudo ./install.sh --python /opt/rpi-logger/env/envs/logger/bin/python3
```

The installer copies the application to:

```text
/opt/dpslogger
```

and creates command wrappers in:

```text
/usr/local/bin
```

---

## Main commands

```text
dps-logger          Log one or more DPS sensors
dps-term            Interactive terminal
dps-scan            Scan RS-485 addresses
dps-read            Read one sensor once
dps-set-address     Change sensor address
dps-unit            Read or change engineering unit
dps-autoread-off    Disable autoread mode on the bus
dps-plot            Generate plots and statistics from CSV
dps-port-check      Check serial port configuration
dps-loopback-test   Serial loopback test
dps-setup-udev      Install udev rules
dps-serial-debug    Low-level serial debug utility
```

---

## Typical workflow

1. Disable autoread if necessary:

```bash
dps-autoread-off
```

2. Scan the bus:

```bash
dps-scan --port /dev/ttyUSB0
```

3. Read one sensor:

```bash
dps-read --port /dev/ttyUSB0 --addr 1
```

4. Start logging:

```bash
mkdir -p ~/data
cd ~/data

dps-logger --port /dev/ttyUSB0 --addr 1
```

5. Generate plots:

```bash
dps-plot dps_addr01_*.csv
```

---

## Notes

* `/opt/dpslogger` is reserved for the installed application.
* Measurement data should always be written to a user-owned directory.
* The tools do not implement a serial-port lock.
* Only one process should normally access a serial device at a time.

---

## Example data

The `examples/` directory contains a complete measurement session with:

* CSV data
* pressure plot
* histogram
* regression plot
* statistics file
* logger metadata

See `examples/README.md` for details. 

---

## Version

Current package version:

```text
2.2
```
