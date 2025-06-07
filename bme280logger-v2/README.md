# BME280Logger‑V2  (v2.2)

BME280Logger‑V2 is an advanced Python data‑logger for Raspberry Pi that collects temperature, relative‑humidity and pressure data from up to **two BME280 sensors**.
Version **2.2** adds reliability‑focused changes such as *Bosch‑recommended FORCED‑mode measurements*, *automatic soft‑reset* and cleaner relay handling.

---

## 0  What’s new in v2.2 (compared with v2.1)

| Area            | v2.1                               | **v2.2**                                                                               |
| --------------- | ---------------------------------- | -------------------------------------------------------------------------------------- |
| Sensor drive    | Normal / continuous mode           | **FORCED mode** every measurement ⇒ lower self‑heating and power                       |
| Recovery        | Relay power‑cycle only             | **Soft‑reset (0×B6) → relay power‑cycle** if needed                                    |
| Register access | `board.I2C` only                   | Adds **`smbus2`** for direct register writes/reads                                     |
| Relay API       | `all_open()/all_close()` only      | Can now toggle **individual channels** (`ch_open/close`) for per‑sensor ground control |
| Cool‑down       | Hard‑coded messages                | Better status messages; NaNs logged while in cool‑down window                          |
| Error log       | Could raise duplicate object error | Guard added so only one `sensor_failures.log` instance is created                      |
| Docs            | Described v2.1 feature set         | **README updated** (you’re reading it!)                                                |

*(Internal version string on the CLI banner has also bumped to **2.2**.)*

---

## 1  Program Overview

BME280Logger‑V2 runs from the command‑line and:

* **Auto‑detects** sensors at I²C addresses `0x76` and `0x77`.
* Triggers a **single FORCED measurement** each interval — the mode Bosch recommends for ≤1 Hz sampling.
* If a read fails it attempts **one soft‑reset**; if that fails it toggles the relay that powers the affected sensor.
* After **5 consecutive failures** the sensor enters a **cool‑down** period (default 1 h, configurable for testing).
* Supports per‑sensor **calibration curves** stored in `calibration.db` (temperature, RH and pressure).
* Logs to CSV (memory‑buffered for up to 60 days) and can optionally create graphs on exit.
* Includes a **simulation mode** (`-simfail`) that randomly opens a relay to test recovery logic.

---

## 2  Hardware Requirements

| Component            | Notes                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------- |
| Raspberry Pi         | Any model with I²C bus `/dev/i2c‑1`                                                               |
| BME280 sensor(s)     | Address jumpers set to `0x76` and/or `0x77`                                                       |
| Relay module         | One channel **per sensor ground** *(or VCC)*; default GPIOs: **21 → sensor 1**, **20 → sensor 2** |
| (Optional) 3rd relay | Use if you also want to cut the shared 3.3 V power line                                           |

Wiring schemes that cut either **GND** *or* **VCC** per sensor are supported; FORCED‑mode keeps average current very low so VCC switching is safe.

---

## 3  Installation

```bash
# Clone just this folder (sparse‑checkout)
git clone --depth 1 --filter=blob:none --sparse https://github.com/kmiikki/sensors.git
cd sensors
git sparse-checkout set bme280logger-v2
cd bme280logger-v2

# Install dependencies
pip install -r requirements.txt  # matplotlib, numpy, smbus2, adafruit‑blinka, etc.
```

---

## 4  Running the Logger

```bash
python bme280logger-v2.py -i 2.0 -b -cal A,1,2 \
  -d /data/logs --ts --simfail
```

### Common CLI options (unchanged)

| Flag               | Description                               | Default |
| ------------------ | ----------------------------------------- | ------- |
| `-i`               | Sampling interval in **seconds**          | `1.0`   |
| `-r`               | Data retention in **days** (RAM)          | `7`     |
| `-nan`             | Keep NaN rows (failed reads) in CSV       | off     |
| `-b` / `-c` / `-a` | Graph types on exit                       | off     |
| `-p`               | Plot calibration curves                   | off     |
| `-simfail`         | Randomly open failure‑relay to test logic | off     |

For the full list run `python bme280logger-v2.py -h`.

---

## 5  Calibration Database

`thpcaldb.py` looks up linear calibration parameters (slope + offset) from `calibration.db` using a **zone letter** and **sensor number**. Specify them with `-cal ZONE,NUM1,NUM2`.  Each enabled calibration adds extra columns (e.g. `Tcal1 (°C)`) to the CSV and live console header.

---

## 6  Troubleshooting Tips

* **Only one sensor found?** Check I²C address jumpers and run `i2cdetect -y 1`.
* **Repeated soft‑reset timeouts?** Your wiring might not supply power quickly enough; try switching VCC instead of GND.
* **Memory usage** grows roughly *72 bytes · samples* for two sensors; the default retention (\~356 MB @ 1 Hz for 60 days) fits in most 1‑GB Pis.

---

## 7  License

MIT License © 2024‑2025 Kim Miikki
