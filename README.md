# Sensors

A collection of sensor-related tools and data loggers for Raspberry Pi–based research instrumentation.

[![DOI](https://zenodo.org/badge/857674737.svg)](https://doi.org/10.5281/zenodo.14542730)

This DOI refers to the **entire Sensors repository**, including all subprojects.

---

## BME280 Data Logger
High-precision environmental logger for T/RH/P using BME280 sensors.

📄 [Project page](CS50x/project)  
🎥 [Video demo](https://youtu.be/62MMcRAne60)

---

## THP Calibration Program
Calibration suite for temperature / humidity sensors.

📄 [Docs](thpcal)  
🎥 [Video demo](https://youtu.be/PUZ_fvgNIi0)

---

## Minimal Datalogger Skeleton
A clean, sensor-agnostic Python datalogger core.

📄 [datalogger-stem](datalogger-stem)

---

## DPS8000 / DPS823A Pressure Logger (NEW)
Full RS-485 pressure logger and simulator for DPS8000/DPS823A sensors.

📄 [dps-pressure-logger](dps-pressure-logger/)  

Includes:
- real DPS interface  
- simulator (noise / saw / sine / settle modes)  
- CSV plotting tools  
- diagnostics utilities  
- udev auto-mapping `/dev/ttyLOG` and `/dev/ttySIM`
