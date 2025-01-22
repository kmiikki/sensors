-- zones definition
CREATE TABLE IF NOT EXISTS zones (
    zone TEXT PRIMARY KEY NOT NULL
);

-- computers definition
CREATE TABLE IF NOT EXISTS computers (
    mac TEXT(17) PRIMARY KEY NOT NULL,
    name TEXT
);

-- Index for computers (mac)
CREATE INDEX idx_computers_mac ON computers(mac);

-- ref_sensors definition
CREATE TABLE IF NOT EXISTS ref_sensors (
    serial_number TEXT PRIMARY KEY NOT NULL,
    ref_name TEXT
);

-- Index for ref_sensors (serial_number)
CREATE INDEX idx_ref_sensors_serial_number ON ref_sensors(serial_number);

-- ref_calibration_dates definition
CREATE TABLE IF NOT EXISTS ref_calibration_dates (
    ref_cal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_calibration_date DATE NOT NULL,
    sn_id TEXT,
    FOREIGN KEY (sn_id) REFERENCES ref_sensors(serial_number)
);

-- Index for ref_calibration_dates (sn_id)
CREATE INDEX idx_ref_calibration_dates_sn_id ON ref_calibration_dates(sn_id);

-- sensors definition
CREATE TABLE IF NOT EXISTS sensors (
    zone TEXT NOT NULL,
    num INTEGER NOT NULL,
    type TEXT NOT NULL,
    address INTEGER NOT NULL,
    computers_id TEXT,
    ref_sn_id TEXT,
    CONSTRAINT comp_key PRIMARY KEY (zone, num),
    FOREIGN KEY (zone) REFERENCES zones(zone) ON DELETE SET NULL,
    FOREIGN KEY (computers_id) REFERENCES computers(mac) ON DELETE SET NULL,
    FOREIGN KEY (ref_sn_id) REFERENCES ref_sensors(serial_number) ON DELETE SET NULL
);

-- Index for sensors (computers_id) and (ref_sn_id)
CREATE INDEX idx_sensors_computers_id ON sensors(computers_id);
CREATE INDEX idx_sensors_ref_sn_id ON sensors(ref_sn_id);

-- calibration_dates definition
CREATE TABLE IF NOT EXISTS calibration_dates (
    cal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    calibration_date DATETIME NOT NULL,
    label TEXT NOT NULL,
    name TEXT NOT NULL,
    name_ref TEXT NOT NULL,
    cal_unit TEXT NOT NULL,
    zone TEXT NOT NULL,
    num INTEGER NOT NULL,
    ref_sn_id TEXT,
    FOREIGN KEY (zone, num) REFERENCES sensors(zone, num) ON DELETE CASCADE,
    FOREIGN KEY (ref_sn_id) REFERENCES ref_sensors(serial_number) ON DELETE SET NULL
);

-- Index for calibration_dates (zone, number) and (ref_sn_id)
CREATE INDEX idx_calibration_dates_zone_number ON calibration_dates(zone, num);
CREATE INDEX idx_calibration_dates_ref_sn_id ON calibration_dates(ref_sn_id);

-- calibration_values definition
CREATE TABLE IF NOT EXISTS calibration_values (
    cal_values_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_value REAL NOT NULL,
    ref_value REAL NOT NULL,
    cal_id INTEGER,
    FOREIGN KEY(cal_id) REFERENCES calibration_dates(cal_id) ON DELETE CASCADE
);

-- Index for calibration_values (cal_id)
CREATE INDEX idx_calibration_values_cal_id ON calibration_values(cal_id);

-- calibration_line definition
CREATE TABLE IF NOT EXISTS calibration_line (
    cal_slopes_id INTEGER PRIMARY KEY AUTOINCREMENT,
    slope REAL NOT NULL,
    const REAL NOT NULL,
    r REAL NOT NULL,
    r_squared REAL NOT NULL,
    std_err REAL NOT NULL,
    p_value REAL NOT NULL,
    cal_id INTEGER,
    FOREIGN KEY(cal_id) REFERENCES calibration_dates(cal_id) ON DELETE CASCADE
);

-- Index for calibration_line (cal_id)
CREATE INDEX idx_calibration_line_cal_id ON calibration_line(cal_id);
