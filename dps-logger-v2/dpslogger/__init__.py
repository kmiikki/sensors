"""dpslogger package.

Core modules for DPS8000 / RS-485 communication, sampling, and CLI tools.
"""

from .transport import SerialTransport, SerialTransportConfig, SerialTransportError, TransactionResult
from .protocol import DPS8000, DPSConfig, DPSProtocolError
from .adapter import DPSAdapter, DPSAdapterConfig, PressureSample

__all__ = [
    "SerialTransport",
    "SerialTransportConfig",
    "SerialTransportError",
    "TransactionResult",
    "DPS8000",
    "DPSConfig",
    "DPSProtocolError",
    "DPSAdapter",
    "DPSAdapterConfig",
    "PressureSample",
]
