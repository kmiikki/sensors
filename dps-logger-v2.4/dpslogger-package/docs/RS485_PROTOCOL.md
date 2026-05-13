# DPS8000 RS-485 Communication Notes

This document describes the practical RS-485 communication behavior used by DPSlogger v2.4 with DPS8000 pressure sensors.

The protocol is an ASCII command interface over an RS-485 bus.

---

## Serial configuration

Typical settings:

```text
Baud rate : 9600
Data bits : 8
Parity    : None
Stop bits : 1
```

This is commonly written as:

```text
9600 8N1
```

DPSlogger defaults for the v2.4 DPS8000 workflow:

```text
eol = cr
command_prefix = one leading space
baudrate = 9600
```

---

## Physical interface

DPS8000 sensors can share one RS-485 bus. Each sensor must have a unique address.

Typical layout:

```text
Computer
│
USB-to-RS485 adapter
│
RS-485 bus
├── DPS8000 sensor address 1
├── DPS8000 sensor address 2
├── DPS8000 sensor address 3
└── DPS8000 sensor address 4
```

Only one process should normally access a serial device at a time.

---

## Command prefix and line ending

DPS8000 commands used here require a leading command prefix. In normal DPSlogger use this is one space character.

Commands are terminated with CR.

Example addressed command as bytes/text:

```text
" 1:G\r"
```

Meaning:

```text
leading space  command prefix
1              sensor address
:              address separator
G              read command
\r            CR terminator
```

DPSlogger appends the configured EOL through the transport layer.

---

## Addressed replies

A typical addressed reply looks like:

```text
01:100.564
```

Meaning:

```text
01       sensor address
100.564  pressure value
```

The logger parses the address prefix and matches replies to the active sensor list.

---

## Useful commands

### Query address

```text
" 1:N,?\r"
```

Typical addressed reply:

```text
01:01
```

### Read pressure

DPSlogger v2.4 can use read command `G` or `R` depending on configuration.

Addressed examples:

```text
" 1:G\r"
" 1:R\r"
```

In the tested DPS8000 setup, `G` is the conservative default used by the v2.4 profiling/logging workflow. `R` may return the current/latest reading faster on some devices, but behavior should be tested before relying on it.

### Query unit

```text
" 1:U,?\r"
```

Example reply:

```text
01:2
```

### Set unit

```text
" 1:U,2\r"
```

Some DPS8000 unit set commands may not return a normal reply. DPSlogger accepts this if a follow-up `U,?` query reports the requested code.

---

## Verified unit mapping

The v2.4 workflow uses the unit mapping verified by unit probing:

```text
0 = mbar
1 = Pa
2 = kPa
3 = MPa
4 = hPa
5 = bar
```

The unit map stored in `dps_config.json` is the source of truth for the logger.

---

## Unit probe policy

During profiling, DPSlogger can probe unit codes 0..5 for each active sensor.

The policy is:

```text
send U,<code>
verify with U,?
accept if U,? reports the requested code
restore the initial unit after probing
```

This handles devices where the `U,<code>` set command itself times out or returns no normal response, but the setting is actually applied.

---

## Burst read mode

In burst mode, DPSlogger sends addressed read commands to all active sensors with a short command gap, then collects replies during a configured timeout window.

Simplified sequence for four sensors:

```text
send " 1:G\r"
wait command_gap_s
send " 2:G\r"
wait command_gap_s
send " 3:G\r"
wait command_gap_s
send " 4:G\r"
collect replies until collect_timeout_s
```

Replies may arrive out of address order. The logger uses the address prefix to assign each reply to the correct logical sensor ID.

---

## Timing observations

In the tested four-sensor DPS8000 setup, one sensor was slower than the others.

Typical observed behavior:

```text
addr01 / p1: about 3.5 s latency
addr02 / p2: about 0.9–1.0 s latency
addr03 / p3: about 1.0 s latency
addr04 / p4: about 0.9–1.0 s latency
```

Safe default configuration:

```text
collect_timeout_s = 5.0
interval_s = 10.0
```

A 5 s interval has also worked in practical testing for this setup, but 10 s is the safer default.

---

## Autoread / autosend mode

Some sensors may continuously transmit data if an automatic send mode is enabled.

This can make manual debugging difficult because incoming data appears while commands are being typed.

Use:

```bash
dps-autoread-off
```

before scanning, address changes, or interactive terminal debugging if the bus is noisy.

---

## Debugging tools

Useful commands:

```text
dps-port-check
dps-autoread-off
dps-scan
dps-read
dps-term
dps-serial-debug
dps-loopback-test
```

Typical debugging order:

```bash
dps-port-check
dps-autoread-off
dps-scan
dps-read --addr 1
dps-term
```

---

## Notes

The exact command set and timing behavior may vary between DPS firmware versions.

DPSlogger v2.4 stores the tested transport, readout, unit map, and timing settings in `dps_config.json`.
