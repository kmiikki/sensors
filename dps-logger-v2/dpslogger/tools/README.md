# DPS Logger Tools

Utility tools for DPS Logger setup and diagnostics.

## Tools

### port_check.py
Checks that the DPS Logger serial port exists and can be opened.

Typical target: `/dev/ttyLOG`.

### loopback_test.py
Serial loopback diagnostic between two ports.

Typically used with:

- TX: `/dev/ttyLOG`
- RX: `/dev/ttySIM`

Verifies raw serial communication, not the DPS protocol.

### setup_udev.py
Interactive tool for creating udev rules that map USB serial adapters to:

- `/dev/ttyLOG`
- `/dev/ttySIM`

Requires root privileges.
