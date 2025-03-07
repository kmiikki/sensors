# BME280Logger-V2

BME280Logger-V2 is an advanced data logging script for collecting and analyzing environmental data (temperature, humidity, and pressure) from BME280 sensors. This version introduces significant improvements over `bme280logger.py`, making data collection more robust, efficient, and configurable.

---

## 1. Program Description

BME280Logger-V2 is designed to interact with one or two BME280 sensors on a Raspberry Pi. It features automatic sensor detection, enhanced calibration handling, and improved data logging capabilities.

### Key Features:
- **Automatic Sensor Detection**: Scans the I2C bus for connected BME280 sensors (0x76 and 0x77) and detects failures.
- **Sensor Reboot via Relay**: If a sensor fails five consecutive times, relays are used to reboot the sensor, followed by a 1-hour cooldown.
- **Multi-Point Calibration**: Supports calibration for temperature, humidity, and pressure via `thpcaldb.py`.
- **Enhanced Logging**:
  - Retains data in memory for up to 60 days (configurable via `-r`).
  - Logs data to CSV with dynamic headers based on available calibration types.
  - Supports optional live console output.
- **Graphing Options**: 
  - Basic figures for single sensors.
  - Combo graphs for comparing two sensors.
  - Calibration plots for verification.
- **Simulation Mode**: Includes `-simfail` to simulate random sensor failures for testing relay-based recovery.

---

## 2. Differences Between Version 1 and Version 2

### Sensor Handling:
- **Version 1:** Required manual sensor configuration.
- **Version 2:** Auto-detects sensors and supports relay-based reboots.

### Calibration:
- **Version 1:** No calibration support.
- **Version 2:** Supports calibration of temperature, relative humidity, and pressure via `thpcaldb.py`.

### Data Retention:
- **Version 1:** Data was logged without memory retention.
- **Version 2:** Stores up to 60 days of data in memory for improved performance.

### Logging Improvements:
- **Version 1:** Basic CSV logging.
- **Version 2:** CSV headers dynamically adjust based on active calibrations.

### Graphing Capabilities:
- **Version 1:** Limited to basic plots.
- **Version 2:** Supports multiple graph types, including calibration plots.

---

## 3. Getting Started

### Prerequisites:
- Raspberry Pi with Python 3.x
- BME280 sensor(s) connected via I2C
- Relay module for reboot functionality (optional but recommended)

### Installation:
1. Clone the repository:
   ```bash
   git clone https://github.com/kmiikki/sensors.git
   cd sensors/bme280logger-v2
   ```
   **OR**, if you only want the `bme280logger-v2` folder, use sparse checkout:
   ```bash
   git clone --depth 1 --filter=blob:none --sparse https://github.com/kmiikki/sensors.git
   cd sensors
   git sparse-checkout set bme280logger-v2
   cd bme280logger-v2
   ```

2. Install required Python libraries:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Program:
The program is configured via command-line arguments:

#### Command-Line Arguments:
- `-d` (str): File base directory (default: current working directory).
- `-s` (bool): Enable datetime subdirectories.
- `-ts` (bool): Add timestamp as a prefix for files.
- `-i` (float): Measurement interval in seconds (default: 1.0).
- `-nan` (bool): Log failed readings as NaN (default: False).
- `-r` (int): Data retention period in memory in days (default: 7).
- `-b` (bool): Create basic graphs for single sensor data.
- `-c` (bool): Create graphs for two sensors (pair, difference, etc.).
- `-a` (bool): Create all graphs (basic and combo) for up to 2 sensors.
- `-p` (bool): Plot calibration graphs.
- `-simfail` (bool): Simulate random sensor failures with relays.
- `-cal` (str): Specify calibrated sensors as `zone,num1,num2`. Example: `-cal A,1,2`.

#### Example Usage:
```bash
python bme280logger-v2.py -d /data/logs -i 2.0 -b -cal A,1,2
```

---

## 4. Notes

- **Version 2** introduces major efficiency improvements for sensor management, calibration, and logging.
- The `calibration.db` file is used to store calibration data. If unavailable, raw sensor values are logged.
- Relative Humidity values are clamped between 0% and 100% to ensure valid readings.
- Future updates may include additional storage formats and improved sensor failure recovery.

