# copy\_pys2tools.py – Deployment Helper for the *sensors* Repository

## Overview

`copy_pys2tools.py` is a lightweight deployment utility tailored for the [**sensors**](https://github.com/kmiikki/sensors/) project.  Its primary task is to gather every Python script in the repository and stage them in a single executable directory—by default `/opt/tools`—so that data‑logger hosts and other machines can run the latest utilities without installing the whole repository.

Key features

* **Automatic discovery & copying** of all `*.py` files (unless explicitly excluded)
* **Extra inclusions / exclusions** controlled via an optional `pysdeploy.lst` file
* **Skips directories suffixed `.old`** to avoid stale backups
* **Preserves timestamps** and applies `ugo+rx` (read + execute) permissions on each copied file
* Runs with **zero external dependencies** aside from Python ≥3.9

---

## Prerequisites

| Requirement                               | Notes                                                             |
| ----------------------------------------- | ----------------------------------------------------------------- |
| Python 3.9 +                              | Uses only the standard library (argparse, pathlib, os, shutil, …) |
| Write access to destination               | Use `sudo` if                                                     |
| `/opt/tools` isn’t writable by your user. |                                                                   |
| (Optional) `git`                          | To clone the *sensors* repository.                                |

---

## Quick Start

```bash
# 1 – Obtain the sources
git clone https://github.com/kmiikki/sensors.git
cd sensors

# 2 – (Optional) define deployment rules
nano pysdeploy.lst

# 3 – Deploy scripts (default → /opt/tools)
sudo python copy_pys2tools.py
```

### Custom destination

```bash
python copy_pys2tools.py -d ~/bin
```

### Force overwrite & quiet mode

```bash
python copy_pys2tools.py -f -q
```

---

## `pysdeploy.lst` Format

`copy_pys2tools.py` looks for `pysdeploy.lst` in the current directory. The
file uses two optional sections:

```text
[Exclude]
# Omit these directories (names must end with "/")
venv/
build/
legacy.old/
# Omit these individual files
secret_config.py

[Include]
# Copy these additional files (any extension)
init.sql
deploy.sh
extra_report.ipynb
```

* **`[Exclude]`**

  * A line ending in `/` → a directory name to skip entirely (relative to project root).
  * A bare filename (or relative path) → a single file to omit.
* **`[Include]`**

  * Lines list **extra files** (with any extension) to copy in addition to the
    default `*.py` set.
  * Paths are interpreted relative to the working directory.
* Blank lines and `#` comments are ignored.

---

## Command‑line Options

| Option       | Shorthand | Purpose                                      |
| ------------ | --------- | -------------------------------------------- |
| `--dest DIR` | `-d DIR`  | Destination directory (default `/opt/tools`) |
| `--force`    | `-f`      | Overwrite even if destination file is newer  |
| `--quiet`    | `-q`      | Suppress informational output                |

---

## How It Works

1. **Discovery** – The script walks the working directory (recursively) with
   `os.walk`, pruning directories that:

   * match an entry in `[Exclude]`, or
   * end with `.old`.
2. **Selection** – For each file:

   * Copy if its extension is `.py` **and** it is *not* listed in
     `[Exclude]`.
   * Additionally copy any file matched by `[Include]`.
3. **Copy & fix permissions** – `shutil.copy2` clones the file with metadata,
   then `os.chmod` bit‑wise ORs read + execute for user, group, and others.
4. **Skip up‑to‑date targets** unless `--force` was specified.

---

## Example Walkthrough

Assume this layout:

```
sensors/
├── bme280logger.py
├── tools/
│   └── copy_pys2tools.py
├── legacy.old/
│   └── unused.py
├── build/
│   └── artefact.py
└── pysdeploy.lst
```

With the following `pysdeploy.lst`:

```
[Exclude]
build/

[Include]
setup_database.sql
```

Running `copy_pys2tools.py` copies:

* `bme280logger.py` (automatic)
* `tools/copy_pys2tools.py` (automatic)
* `setup_database.sql` (manual include)

It **skips** everything in `legacy.old/` and the entire `build/` directory.

---

## Troubleshooting

* **“Permission denied”** → Run with `sudo` or change destination ownership.
* **File not copied** → Check `[Exclude]` rules and path spelling.
* **Rule does not work** → Remember directory rules need trailing `/`.

---

## License

This utility inherits the main *sensors* repository licence (MIT).  See
[`LICENSE`](../LICENSE) for details.

---

© 2024–2025 Kim Miikki