# DPS Logger Quick Start

This guide shows the typical workflow for using DPS Logger with a DPS RS-485 pressure sensor.

---

# 1 Connect the sensor

Connect the RS-485 adapter and the DPS sensor to the computer.

Typical serial device names used in this project include:

```

/dev/ttyLOG
/dev/ttyUSB0
/dev/ttyACM0

````

`/dev/ttyLOG` is a stable device name created using a udev rule.

Using default Linux device names such as `/dev/ttyUSB0` or `/dev/ttyACM0` also works, but the device number may change when:

- USB devices are reconnected
- multiple USB serial adapters are present
- the system is rebooted

For reliable operation, especially in automated measurements, using a fixed device name such as `/dev/ttyLOG` is recommended.

A udev rule can be installed with:

```bash
sudo dps-setup-udev
````

---

# 2 Check the serial port

Verify that the serial device exists and is accessible:

```bash
dps-port-check
```

If the port is not detected, check:

* USB-RS485 adapter connection
* udev configuration
* user permissions (dialout group)

---

# 3 Scan the RS-485 bus

Find sensors connected to the bus:

```bash
dps-scan
```

Example output:

```
Found device at address 1
```

---

# 4 Read a pressure value

Test communication with the sensor:

```bash
dps-read --addr 1
```

Example output:

```
Pressure: 1.00652 bar
```

If this works, communication with the sensor is functioning correctly.

---

# 5 Record measurements

Start logging pressure data:

```bash
dps-logger --addr 1
```

The logger writes measurements to a CSV file such as:

```
dps_addr01_YYYYMMDD-HHMMSS.csv
```

---

# 6 Generate plots

Create plots and statistics from the recorded data:

```bash
dps-plot dps_addr01_YYYYMMDD-HHMMSS.csv
```

Generated files include:

```
*_pressure.png
*_hist.png
*_regression.png
*_stats.txt
```

Example output files are available in the `examples/` directory.

---

# Interactive terminal (optional)

For manual communication and debugging:

```bash
dps-term
```

This allows sending commands directly to the sensor.

---

# Troubleshooting serial ports

If the sensor is not detected:

1. Check available serial devices:

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

2. Verify user permissions:

```bash
groups
```

Your user should belong to the `dialout` group.

3. If needed, reconnect the USB-RS485 adapter and run `dps-scan` again.

---

# More information

Detailed command descriptions are available in:

```
docs/CLI_REFERENCE.md
```

