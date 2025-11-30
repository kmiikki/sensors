# DPS Pressure Logger for Raspberry Pi

A high-precision datalogger and simulator for DPS8000/DPS823A RS-485 pressure sensors.

This package includes:
- ⚙️ **DPS datalogger** (`dps_logger.py`)
- 🔄 **RS-485 pressure simulator** (`rs485_pressure_sim.py`)
- 📈 **CSV plotting tool** (`plot_dps_csv.py`)
- 🩺 **diagnostic utilities** (port check, smoke test, loopback)
- 🌡 **optional Raspberry Pi thermal monitoring**
- 🔧 automatic udev port mapping: `/dev/ttyLOG` and `/dev/ttySIM`

Designed for reproducible research, stable timing, and long unattended logging.

---

## Features

### ✔ DPS Logger (`dps_logger.py`)
- drift-free deterministic timing using `perf_counter()`
- waits for next second boundary before starting
- robust Ctrl+C handler (completes ongoing cycle first)
- real UNIX timestamps + ISO timestamps
- optional thermal CPU readings
- compatible with both real DPS sensor and simulator

### ✔ RS-485 Pressure Simulator (`rs485_pressure_sim.py`)
Provides realistic sensor behaviour for development:

| Mode     | Description |
|----------|-------------|
| `noise`  | Gaussian noise around a center |
| `saw`    | Periodic sawtooth, p1 → p2 |
| `sine`   | Smooth sinusoidal wave |
| `settle` | Exponential settling: p(t)=p2+(p1−p2)·exp(−t/τ) |

Example plots are found in `examples/`.

### ✔ CSV Plotting (`plot_dps_csv.py`)
- plots pressure vs. time
- optional `--temp` overlays CPU temperature on secondary axis
- units shown as `(bar)` instead of `[bar]`

Example:
```
plot_dps_csv.py log.csv --dpi 200
```

---

## Installation

Clone the repository:

```
git clone https://github.com/kmiikki/sensors
cd sensors/dps-pressure-logger
```

Install dependencies:

```
micromamba install -y python=3.11 pyserial numpy matplotlib
```

Install udev rules:

```
sudo python setup_dps_logger_udev.py
sudo udevadm control --reload-rules
```

After installation:
- `/dev/ttyLOG` = real DPS sensor  
- `/dev/ttySIM` = simulator  

---

## Using the Simulator

### Noise demo
```
rs485_pressure_sim.py --port /dev/ttySIM --mode noise --p1 1.0
```

### Sawtooth
```
rs485_pressure_sim.py --port /dev/ttySIM --mode saw --p1 0.9 --p2 1.4 --period 12
```

### Sine wave
```
rs485_pressure_sim.py --port /dev/ttySIM --mode sine --p1 1.0 --amp 0.2 --period 30
```

### Exponential settling
```
rs485_pressure_sim.py --port /dev/ttySIM --mode settle --p1 1.5 --p2 1.0 --tau 30
```

Example plots are stored in `examples/`.

---

## Example: Logging

```
dps_logger.py --base-dir ./logs --prefix dps --interval 1.0 --unit bar
```

Graceful shutdown:
- Press **Ctrl+C**  
- Logger finishes current cycle  
- Closes cleanly  

---

## Example: Plotting

Basic plot:
```
plot_dps_csv.py log.csv
```

Plot with CPU temperature:
```
plot_dps_csv.py log.csv --temp
```

High-resolution PNG:
```
plot_dps_csv.py log.csv --dpi 200
```

---

## Development Tools

Additional optional utilities are stored in `tools/`.

### `tools/dyn_step_test.py`
Generates dynamic step-response datasets for simulator testing.  
Not required for normal operation, logging, or plotting.

---

## License
MIT License. See `LICENSE` for details.

