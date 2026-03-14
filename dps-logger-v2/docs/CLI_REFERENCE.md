# DPS Logger Command Reference

This document describes the command-line tools included in DPS Logger.

All commands support the `--help` option for detailed usage information.

---

# Common options

Most commands support the following options.

### Serial port

Specify the serial device:

```

--port DEVICE

```

Examples:

```

--port /dev/ttyLOG
--port /dev/ttyUSB0
--port /dev/ttyACM0

```

If not specified, the default port `/dev/ttyLOG` is used.

### Sensor address

Specify the RS-485 device address:

```

--addr ADDRESS

```

Example:

```

--addr 1

```

---

# Default values

Unless specified otherwise, the following default values are used:

| Option | Default |
|------|------|
| serial port | `/dev/ttyLOG` |
| sensor address | `1` |
| baudrate | `9600` |
| timeout | `1.0 s` |
| logging interval | `1.0 s` |
| output directory | current directory |
| filename prefix | `dps` |

---

# dps-scan

Scan the RS-485 bus for connected sensors.

This command sends discovery queries to the bus and reports responding device addresses.

### Example

```

dps-scan

```

Example output:

```

Found device at address 1
Found device at address 3

```

Use this command before communicating with a sensor to determine its address.

---

# dps-read

Read a single pressure value from a sensor.

### Examples

```

dps-read --addr 1

```

Using a specific serial port:

```

dps-read --port /dev/ttyUSB0 --addr 1

```

Example output:

```

Pressure: 1.00652 bar

```

This command is useful for verifying communication with a sensor.

---

# dps-logger

Record pressure measurements continuously and write them to a CSV file.

### Example

```

dps-logger --addr 1

```

Optional arguments:

```

--interval SECONDS

```

Polling interval for a full measurement cycle.

Example:

```

dps-logger --addr 1 --interval 0.5

```

The logger writes measurements to a file named like:

```

dps_addr01_YYYYMMDD-HHMMSS.csv

```

The CSV file contains timestamped pressure measurements.

---

# dps-plot

Generate plots and statistics from a CSV measurement file.

### Example

```

dps-plot measurement.csv

```

The command generates the following files:

```

*_pressure.png
*_hist.png
*_regression.png
*_stats.txt

```

These files visualize the recorded measurement data.

Example output files are available in the `examples/` directory.

---

# dps-set-address

Change the RS-485 address of a sensor.

### Example

```

dps-set-address --old 1 --new 2

```

Use this command when multiple sensors share the same bus and unique addresses are required.

---

# dps-term

Interactive terminal for communicating directly with the sensor.

### Example

```

dps-term

```

This mode allows sending commands manually and viewing raw device responses.

It is primarily intended for debugging and protocol exploration.

---

# Diagnostic tools

Additional setup and diagnostic utilities are included in:

```

dpslogger/tools/

```

These commands help verify the serial interface and system configuration.

---

## dps-port-check

Verify that the serial port exists and can be opened.

Example:

```

dps-port-check

```

---

## dps-loopback-test

Test RS-485 loopback communication using two serial ports.

Example:

```

dps-loopback-test

```

---

## dps-setup-udev

Install a udev rule to create a stable serial device name such as:

```

/dev/ttyLOG

```

Example:

```

sudo dps-setup-udev

```

Administrator privileges are required.

