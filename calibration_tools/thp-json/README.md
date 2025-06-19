# THP JSON Calibration Dictionary (`thpcal.json`)

This folder contains the JSON-based calibration infrastructure used by all
**THP** (Temperature, Humidity, Pressure) tools in the `sensors` project.

```

calibration_tools/thp-json/
├── thpcaldb.py   ← lightweight helper module
└── README.md     ← you are here

````

## 1. Why a JSON dictionary?

* **Single source of truth** – one file stores the latest linear calibration
  coefficients for every sensor and every measurement type.
* **Tool-agnostic** – the same file is consumed by:
  * `t-analysis.py`, `rh-analysis.py`, `thp-t-flats.py`
  * `thp-calibrate.py` (offline calibrator)
  * `bme280logger-v2.py` (live Raspberry Pi logger)
* **Version-controlled** – easy to review & diff in Git.

## 2. File discovery

Each program looks for **`thpcal.json`** in the following order:

1. Current working directory  
2. One directory up (`..`)  
3. `/opt/tools` *(for packaged/installed systems)*

The first match wins. If none is found the tool falls back to its original
SQLite database (analysis scripts still *write* a new JSON).

## 3. JSON structure

```jsonc
{
  "1": {                 // sensor number (int → string in JSON)
    "C3": {              // sensor code  (zone + number)
      "T": {             // Temperature block
        "label": "Temperature",
        "slope": 1.005,
        "constant": -0.12,
        "r2": 0.999847
      },
      "RH": {            // Relative-humidity block  (alias "H" accepted)
        "label": "Relative Humidity",
        "slope": 0.987,
        "constant": 1.23
      }
      /* "P" block optional */
    }
  },

  "2": {
    "C4": {
      "T":  { ... },
      "P":  { ... }      // Pressure block
    }
  }
}
````

* **Outer keys** – integer sensor numbers as **strings** (JSON restriction).
* **Second level** – sensor codes (`A7`, `C11`, …).
* **Third level** – measurement type keys:

  * `T` = temperature
  * `RH` or `H` = relative humidity
  * `P` = pressure
* Each block stores at minimum:
  `slope`, `constant` (alias `const`), optionally `r2`, `label`.

### Minimum valid entry

```json
{ "slope": 1.000, "constant": 0.0 }
```

## 4. Behaviour in each tool

| Tool / Script                                                   | What happens with `-cal Z,N1[,N2]`                                                                                                                                                        |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`t-analysis.py`, `rh-analysis.py`, `rh-linreg.py`, `thp-t-flats.py`** | Results are merged **into** `thpcal.json` (creating or updating the `"T"` / `"RH"` blocks).                                                                                               |
| **`thp-calibrate.py`**                                          | *Per sensor*: if **any** entry for that sensor exists in JSON, **all** JSON values are used; otherwise the legacy SQLite database supplies all types.                                     |
| **`bme280logger-v2.py`**                                        | Same rule as `thp-calibrate.py` – JSON first, DB only if the sensor is absent from the file. Logger prints the source (“thpcal.json” or “database”) and the calibrated types on start-up. |

> **Clamping:** For humidity calibrations, results are automatically clipped
> to **0 – 100 %** in every tool.

## 5. Updating calibrations

1. Run the relevant analysis tool with the `-cal` flag, e.g.:

   ```bash
   python t-analysis.py -cal C,3
   ```

2. Commit the modified **`thpcal.json`** (review the diff for sanity):

   ```bash
   git add calibration_tools/thp-json/thpcal.json
   git commit -m "Update calibration for C3 temperature"
   ```

## 6. API helper (`thpcaldb.py`)

* Re-exports the legacy **`Calibration`** class (SQLite) and
  `parse_zone_numbers()` utility.
* Analysis scripts import only `parse_zone_numbers` here – all JSON read/write
  code is embedded in the scripts for minimal dependencies.
* Future extensions (e.g. date stamping, multi-point curves) should go into
  this module and the JSON schema.

## 7. Compatibility & fallbacks

* Tools remain **backward-compatible** – if no JSON file is found they behave
  exactly as before.
* Mixing JSON with DB *per sensor* is prohibited to avoid hidden
  inconsistencies.

## 8. Version history

| Date (UTC) | Change                                                                                                               |
| ---------- | -------------------------------------------------------------------------------------------------------------------- |
| 2025-06-18 | Initial JSON write-support in analysis scripts (`t-analysis`, `rh-analysis`, `rh-linreg`, `thp-t-flats`).            |
| 2025-06-19 | Read-support added in `thp-calibrate.py` and `bme280logger-v2.py`. Multi-type (`T`, `RH`, `P`) handling implemented. |

---

Questions or suggestions?
Open an issue on the main repository or ping **@kmiikki**.
