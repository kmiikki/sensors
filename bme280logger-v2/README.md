

# BME280Logger‑V2  (v2.4)

BME280Logger‑V2 is an advanced Python data‑logger for Raspberry Pi that collects temperature, relative‑humidity and pressure data from up to **two BME280 sensors**.

Version **2.4** builds on the reliability improvements of 2.2 by adding a JSON‑based calibration workflow (2.3) and automatic plotting of calibrated data (2.4).\
A small **patch released 2025‑06‑26** fixes where calibration plots (`-p`) are stored when the date‑time sub‑directory flag (`-s`) is enabled.

---

## 0  What’s new

| Area               | 2.2                          | 2.3                                                                                | **2.4**                                                                                  |
| ------------------ | ---------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Calibration source | SQLite `calibration.db` only | **Adds **`` as an alternative source (same schema) – handy for quick edits         | Unchanged                                                                                |
| Calibration types  | One type per sensor          | **Multiple calibration types per sensor** (T, RH, P) → dynamic CSV/console columns | Unchanged                                                                                |
| Graphs             | Raw values only              | Raw values only                                                                    | **Graphs now prefer calibrated values** (if available) and label axes accordingly        |
| Extra plots        | –                            | –                                                                                  | ``** flag** generates calibration‑specific plots (cal‑vs‑raw & sensor‑pairs)             |
| Log files          | Sensor/error logs            | + Calibration logs describing parameters & sources                                 | Calibration log now records calibration‑plot directory                                   |
| Plot location      | –                            | –                                                                                  | **FIX:** When `-s` is used the `cal` directory is created under the date‑time sub‑folder |

*(See the ****changelog**** section below for full details.)*

---

## 1  Program Overview

BME280Logger‑V2 runs from the command‑line and:

- **Auto‑detects** sensors at I²C addresses `0x76` and `0x77`.
- Triggers a **single FORCED measurement** each interval — the mode Bosch recommends for ≤ 1 Hz sampling.
- If a read fails it attempts **one soft‑reset**; if that fails it toggles the relay that powers the affected sensor.
- After **5 consecutive failures** the sensor enters a **cool‑down** period (default 1 h, configurable for testing).
- Supports per‑sensor **calibration curves** stored in `calibration.db` **or** `thpcal.json`. Each enabled calibration adds extra columns (e.g. `Tcal1 (°C)`) to the CSV and live console header.
- **v2.4** automatically substitutes calibrated values in *all* standard graphs; raw data is used only where calibration is missing. Use `` to emit dedicated calibration plots.
- Logs to CSV (memory‑buffered for up to 60 days) and can optionally create graphs on exit.
- Includes a **simulation mode** (`-simfail`) that randomly opens a relay to test recovery logic.

---

## 2  Hardware Requirements

| Component            | Notes                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| Raspberry Pi         | Any model with I²C bus `/dev/i2c‑1`                                                               |
| BME280 sensor(s)     | Address jumpers set to `0x76` and/or `0x77`                                                       |
| Relay module         | One channel **per sensor ground** *(or VCC)*; default GPIOs: **21 → sensor 1**, **20 → sensor 2** |
| (Optional) 3rd relay | Use if you also want to cut the shared 3.3 V power line                                           |

Wiring schemes that cut either **GND** *or* **VCC** per sensor are supported; FORCED‑mode keeps average current very low so VCC switching is safe.

---

## 3  Installation

```bash
# Clone only this folder (sparse‑checkout)
git clone --depth 1 --filter=blob:none --sparse https://github.com/kmiikki/sensors.git
cd sensors
git sparse-checkout set bme280logger-v2
cd bme280logger-v2

# Install dependencies
pip install -r requirements.txt   # matplotlib, numpy, smbus2, adafruit‑blinka, etc.
```

---

## 4  Running the Logger

```bash
python bme280logger-v2.py -i 2.0 -b -cal A,1,2 -p -s \
  -d /data/logs --ts --simfail
```

### Common CLI options (updated)

| Flag               | Description                                                                                                   | Default |
| ------------------ | ------------------------------------------------------------------------------------------------------------- | ------- |
| `-i`               | Sampling interval in **seconds**                                                                              | `1.0`   |
| `-r`               | Data retention in **days** (RAM)                                                                              | `7`     |
| `-nan`             | Keep NaN rows (failed reads) in CSV                                                                           | off     |
| `-b` / `-c` / `-a` | Graph types on exit (basic, combo, all)                                                                       | off     |
| `-p`               | **Generate calibration plots** (cal‑vs‑raw & inter‑sensor)                                                    | off     |
| `-s`               | **Create a date‑time sub‑directory** (e.g. `20250625‑1412`) under the base directory and save all files there | off     |
| `-d DIR`           | Base directory for CSV, logs & graphs                                                                         | *cwd*   |
| `--ts`             | Prefix file names with date‑time stamp                                                                        | off     |
| `-cal Z,N1,N2`     | Enable calibration for up to 2 sensors (zone, num1, num2)                                                     | –       |
| `-simfail`         | Randomly open the failure‑relay to test recovery logic                                                        | off     |

> **Plot output directory:**\
> *Without* `-s` calibration graphs go to `<base>/cal`.\
> *With* `-s` they go to `<base>/<YYYYMMDD‑HHMM>/cal` where *YYYYMMDD‑HHMM* is the run’s start timestamp.

For the full list run:

```bash
python bme280logger-v2.py -h
```

---

## 5  Calibration Sources

### 5.1  SQLite database (`calibration.db`)

The original method. `thpcaldb.py` looks up linear calibration parameters (slope + offset) using a **zone letter** and **sensor number**.

### 5.2  JSON file (`thpcal.json`) — **new in v2.3**

Place a `thpcal.json` next to the script (or in its parent or `/opt/tools`). The layout mirrors the DB schema but in convenient plain text:

```json
{
  "2025": {
    "A1": { "T": { "slope": 0.9981, "constant": 0.15 } },
    "A2": { "RH": { "slope": 1.021, "constant": -2.3 },
            "P":  { "slope": 0.997, "constant": 1.1 } }
  }
}
```

Both sources can coexist; JSON takes precedence per‑sensor.

*Each enabled calibration adds a **`…cal…`** column to the CSV, and ****v2.4**** ensures all graphs use those values.*

---

## 6  Troubleshooting Tips

- **Only one sensor found?** Check I²C address jumpers and run `i2cdetect -y 1`.
- **Repeated soft‑reset timeouts?** Your wiring might not supply power quickly enough; try switching VCC instead of GND.
- **Memory usage** grows roughly *72 bytes × samples* for two sensors; the default retention (\~356 MB @ 1 Hz for 60 days) fits in most 1‑GB Pis.

---

## 7  Changelog (abridged)

### v2.4  (2025‑06‑25 → patch 2025‑06‑26)

- **Graphs** now automatically select calibrated columns where available.
- `` emits calibration‑centric plots (single, raw‑vs‑cal, pairs).
- **FIX:** Calibration plots honour the `-s` flag and are stored in `<base>/<YYYYMMDD‑HHMM>/cal`.
- Calibration log records the exact plot directory.
- Minor bug‑fixes around header labelling and CLI banner.

### v2.3  (2025‑05‑10)

- Added `` support for portable calibrations.
- Multiple calibration types per sensor; dynamic CSV header.
- Console and log file print calibrated values where available.

### v2.2  (2025‑02‑14)

- Switched to **FORCED‑mode** measurements.
- Pre‑emptive soft‑reset before relay power‑cycle.
- Added *smbus2* for direct register writes.

---

## 8  License

MIT License © 2024‑2025 Kim Miikki

