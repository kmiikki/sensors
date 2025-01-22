# BME280Logger-V2

BME280Logger-V2 is an advanced data logging script for collecting and analyzing environmental data (temperature, humidity, and pressure) from the BME280 sensor. It enhances features from its predecessor, `bme280logger.py`, while improving efficiency and flexibility for various applications.

---

## 1. Program Description

BME280Logger-V2 is designed to interact with a BME280 sensor to collect and manage environmental data. It provides options for real-time calibration, memory-based data retention, and flexible data output.

### Key Features:
- **Sensor Data Collection:** Reads temperature, humidity, and pressure data from the BME280 sensor.
- **Data Storage:** Collected data is stored in a CSV file for long-term storage and analysis.
- **Calibration:** Supports optional calibration for relative humidity via the `calibration.db` file.
- **Flexible Data Retention:** Retains data in memory, logs data to CSV, and includes optional live console output for real-time monitoring.
- **Customizable Parameters:** Allows configuration through command-line arguments for sampling rate, data paths, and calibration offsets.

---

## 2. Differences Between Version 1 and Version 2

### Calibration:
- **Version 1:** Does not support calibrations. Logged data consists solely of factory-calibrated sensor values.
- **Version 2:** Introduces optional calibration for relative humidity via `calibration.db`. Calibration is handled externally and applied dynamically during data processing.

### Data Handling:
- **Version 1:** Data handling is limited to basic logging.
- **Version 2:** Provides flexible CSV-based data storage with optional in-memory retention and live console output.

### Calibration Database:
- **Version 1:** Does not support any calibration databases.
- **Version 2:** Supports a single calibration database (`calibration.db`).

### Performance Improvements:
- Enhanced logging efficiency.
- Reduced memory footprint for high-frequency data collection.
- Streamlined CSV export options.

---

## 3. Getting Started

### Prerequisites:
- Python 3.x
- BME280 sensor

### Installation:
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/bme280logger-v2.git
   ```
2. Install required Python libraries:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Program:
The program is configured via command-line arguments. Below are some of the available options:

#### Command-Line Arguments:
- `-d` (str): File base directory (default: current working directory).
- `-s` (bool): Enable datetime subdirectories.
- `-ts` (bool): Add timestamp as a prefix for files.
- `-i` (float): Measurement interval in seconds (default: 1.0).
- `-nan` (bool): Log failed readings as NaN (default: False).
- `-r` (int): Data retention period in memory in days (default: 30).
- `-b` (bool): Create basic graphs for single sensor data.
- `-c` (bool): Create graphs for two sensors (pair, difference, etc.).
- `-a` (bool): Create all graphs (basic and combo) for up to 2 sensors.
- `-simfail` (bool): Simulate random sensor failures with relays.
- `-cal` (str): Specify calibrated sensors as `zone,num1,num2`. Example: `-cal A,1,2`.

#### Example Usage:
```bash
python bme280logger-v2.py -d /data/logs -i 2.0 -b -cal A,1,2
```

---

## 4. Notes

- **Version 2** focuses on optimized data logging and CSV-based storage.
- Future versions may expand support for additional data storage formats and database systems.
```
