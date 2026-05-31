# DPSlogger v2.4 Quick Start

This guide shows a practical workflow for using DPSlogger v2.4 with DPS8000 pressure sensors on an RS-485 bus.

DPSlogger v2.4 supports both commissioning/debugging tools and the newer multi-sensor logging workflow with automatic profiling and `dps_config.json` generation.

---

## 1. Connect the hardware

Connect the USB-to-RS485 adapter and the DPS8000 sensors.

Typical serial device names are:

```text
/dev/ttyLOG
/dev/ttyUSB0
/dev/ttyACM0
```

`/dev/ttyLOG` is the recommended stable device name. It can be created with the udev setup tool:

```bash
sudo dps-setup-udev
```

If group permissions were changed, log out and log back in.

---

## 2. Check the serial port

Verify that the serial device exists and is accessible:

```bash
dps-port-check
```

If the port is not detected, check the USB adapter, cabling, udev rule, and user group membership.

---

## 3. Quiet the bus if needed

If a sensor is continuously transmitting, manual commands and scanning may be difficult.

Use:

```bash
dps-autoread-off
```

With an explicit port and address range:

```bash
dps-autoread-off --port /dev/ttyUSB0 --start 0 --end 4
```

---

## 4. Scan the RS-485 bus

Find connected sensors:

```bash
dps-scan
```

Example result:

```text
Found device at address 1
Found device at address 2
Found device at address 3
Found device at address 4
```

---

## 5. Test a single read

Read one sensor:

```bash
dps-read --addr 1
```

With an explicit port:

```bash
dps-read --port /dev/ttyUSB0 --addr 1
```

---

## 6. Set addresses or units if needed

Change sensor address:

```bash
dps-set-address --from 1 --to 2
```

Read or set unit:

```bash
dps-unit --addr 1
dps-unit --addr 1 --unit 2
```

For the DPS8000 sensors used in this project, the verified unit mapping is:

```text
0 = mbar
1 = Pa
2 = kPa
3 = MPa
4 = hPa
5 = bar
```

---

## 7. First multi-sensor logging run

In a new measurement directory without `dps_config.json`, run:

```bash
dps-logger --port /dev/ttyLOG --addresses 1,2,3,4 --ids p1,p2,p3,p4 --interval 5 --duration 60
```

If no `dps_config.json` is found, DPSlogger can run automatic profiling:

```text
dps-profile-cycle
→ dps-profile-to-config
→ dps_config.json
→ measurement logging
```

The generated `dps_config.json` contains the bus settings, sensor IDs, addresses, unit mapping, timing recommendations, and profiling metadata.

---

## 8. Later runs with existing config

DPSlogger searches for `dps_config.json` in this order:

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

When the same sensor bus and physical setup are reused, `dps_config.json` can be placed in the parent or grandparent directory.

After the config exists, later runs can be simple:

```bash
dps-logger --duration 60
```

or:

```bash
dps-logger --interval 5 --duration 60
```

---

## 9. Output files

A typical four-sensor run creates:

```text
dps_addr01_<session>.csv
dps_addr02_<session>.csv
dps_addr03_<session>.csv
dps_addr04_<session>.csv
dps_summary_<session>.csv
dps_run_<session>.json
```

If automatic profiling was used, it also creates:

```text
dps_profile_<session>.json
dps_config.json
```

Detail CSV files are address-based. The summary CSV is researcher-friendly and uses logical IDs such as `p1`, `p2`, `p3`, and `p4`.

---

## 10. Plot the latest run

Generate all main plots from the latest session:

```bash
dps-plot --latest --all
```

If the run contains isolated pressure spikes, create plot-cleaned copies first and plot from the cleaned directory:

```bash
dps-clean --plot-clean
dps-plot --dir clean_plot --latest --all
```

The original measurement CSV files are not modified.

Black-and-white output:

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

---

## 11. Plot outputs

A multi-sensor v2.4 plotting run can generate:

```text
dps_addr01_plot_<session>.png
dps_addr02_plot_<session>.png
dps_addr03_plot_<session>.png
dps_addr04_plot_<session>.png
dps_summary_plot_<session>.png
```

Additional diagnostic files may include:

```text
dps_addr01_<session>_hist.png
dps_addr01_<session>_regression.png
dps_addr01_<session>_stats.txt
```

Histograms and regression files are diagnostic outputs. The main researcher-facing plots are the per-sensor pressure-vs-time plots and the combined summary plot.

---

## 12. Example data

A complete four-sensor example run is available in:

```text
../examples/four-sensor-run-20260511-163435/
```

It can be used to test `dps-plot` without connected hardware:

```bash
cd ../examples/four-sensor-run-20260511-163435
dps-plot --dir . --session 20260511-163435 --all
```

It can also be used to test spike cleaning and plotting without connected hardware:

```bash
dps-clean --plot-clean
dps-plot --dir clean_plot --session 20260511-163435 --all
```

The cleaned files are written under `clean_plot/`; the original example CSV files are not modified.

---

## More information

See also:

```text
docs/CLI_REFERENCE.md
docs/RS485_PROTOCOL.md
```
