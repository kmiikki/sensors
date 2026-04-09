# DPS RS-485 Communication Protocol

This document describes the communication protocol used by DPS pressure sensors when accessed through DPS Logger.

The protocol is a simple ASCII-based command interface over an RS-485 serial bus.

---

# Serial configuration

The sensors communicate using the following serial settings:

```

Baud rate : 9600
Data bits : 8
Parity    : None
Stop bits : 1

```

This configuration is commonly written as:

```

9600 8N1

```

---

# Physical interface

Communication uses an RS-485 half-duplex bus.

Multiple sensors can share the same bus, each identified by a unique device address.

Typical system layout:

```

Computer
│
USB-RS485 adapter
│
RS-485 bus
├── Sensor (address 1)
├── Sensor (address 2)
└── Sensor (address 3)

```

---

# ASCII command protocol

Commands and responses are transmitted as ASCII text.

A command typically contains:

```

[address] [command]

```

Example:

```

01 R

```

Where:

```

01   sensor address
R    read pressure command

```

---

# Line termination

Commands are terminated with a newline sequence.

The following termination modes may be used depending on the device configuration:

```

CR
LF
CRLF

```

DPS Logger automatically handles the correct termination mode.

---

# Sensor address

Each sensor on the RS-485 bus has a numeric address.

Example addresses:

```

1
2
3

```

Commands must specify the correct device address when multiple sensors are present.

Example:

```

dps-read --addr 1

```

---

# Typical response

A typical sensor response contains a numeric pressure value.

Example:

```

01:1.00652

```

This indicates a pressure reading of **1.00652 bar** from sensor address **1**.

---

# Automatic measurement mode

Some sensors support an automatic measurement mode where the device periodically transmits readings without a request.

Sending a command typically disables the automatic transmission for a configurable timeout period.

DPS Logger uses explicit read commands to request measurements when logging data.

---

# Timing considerations

RS-485 devices may require short delays between commands.

The DPS Logger transport layer handles these delays automatically to ensure reliable communication.

---

# Debugging communication

For debugging purposes, the following tools may be used:

```

dps-term

```

Interactive terminal for manual commands.

```

dps-port-check

```

Verify serial device access.

```

dps-loopback-test

```

Verify RS-485 adapter functionality.

---

# Notes

The exact command set may vary slightly between firmware versions.

DPS Logger implements the subset of commands required for:

- reading pressure values
- detecting device addresses
- configuring sensor addresses

