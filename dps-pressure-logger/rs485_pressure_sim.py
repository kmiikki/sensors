#!/usr/bin/env python3
from __future__ import annotations
import argparse, math, time, threading, re, sys, random
from dataclasses import dataclass
from typing import Optional, Tuple, Literal
import serial

Mode = Literal["sine", "saw", "settle", "noise", "const"]

@dataclass
class SignalCfg:
    mode: Mode = "settle"
    offset: float = 1.0
    amplitude: float = 0.2
    freq_hz: float = 0.05
    p1: float = 1.5
    p2: float = 1.0
    tau_s: float = 30.0
    noise_std: float = 0.01

class Signal:
    def __init__(self, cfg: SignalCfg):
        self.cfg = cfg
        self.t0 = time.perf_counter()

    def value(self, t: float) -> float:
        c = self.cfg
        if c.mode == "const":
            return c.offset
        if c.mode == "sine":
            return c.offset + c.amplitude * math.sin(2*math.pi*c.freq_hz * (t-self.t0))
        if c.mode == "saw":
            phase = ((t - self.t0) * c.freq_hz) % 1.0
            return c.offset + c.amplitude * (2.0*phase - 1.0)
        if c.mode == "noise":
            return c.offset + random.gauss(0.0, c.noise_std)
        if c.mode == "settle":
            dt_ = max(0.0, t - self.t0)
            return c.p2 + (c.p1 - c.p2) * math.exp(-dt_ / max(1e-6, c.tau_s))
        return c.offset

    def step_to(self, p2_new: float):
        """Uusi askelkohta: aloita asettuminen nykyisestä arvosta p2_new:iin."""
        now = time.perf_counter()
        p_now = self.value(now)
        self.cfg.p1 = p_now
        self.cfg.p2 = p2_new
        self.t0 = now

@dataclass
class DeviceCfg:
    port: str
    baud: int = 9600
    unit: str = "bar"
    addr: int = 0
    autosend: bool = False
    autosend_rate_hz: float = 1.0
    temp_c: float = 25.0
    temp_drift_c_per_min: float = 0.0
    echo_address_in_reply: bool = False

IDENTITY = "DPS8000 SIM, FW 1.0, RS485 ASCII, 0-2 bar abs"
UNITS_ALLOWED = {"bar", "Pa", "kPa", "mbar", "psi"}

_BAR_TO = {"bar":1.0, "Pa":1e5, "kPa":1e2, "mbar":1e3, "psi":14.503773773}

def convert_from_bar(x_bar: float, unit: str) -> float:
    return x_bar * _BAR_TO.get(unit, 1.0)

class DPSSim:
    def __init__(self, dev: DeviceCfg, sig: Signal):
        self.dev = dev
        self.sig = sig
        self.ser: Optional[serial.Serial] = None
        self._stop = threading.Event()
        self._autosend_thr: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_temp_update = time.perf_counter()

    def open(self):
        self.ser = serial.Serial(
            self.dev.port, self.dev.baud,
            timeout=0.1,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            write_timeout=0.2,
            xonxoff=False, rtscts=False, dsrdtr=False
        )
        self._stop.clear()
        if self.dev.autosend:
            self._start_autosend()

    def close(self):
        self._stop.set()
        if self._autosend_thr and self._autosend_thr.is_alive():
            self._autosend_thr.join(timeout=1.0)
        if self.ser:
            try: self.ser.close()
            except Exception: pass
        self.ser = None

    def _start_autosend(self):
        def run():
            period = 1.0 / max(1e-6, self.dev.autosend_rate_hz)
            next_t = time.perf_counter()
            while not self._stop.is_set():
                self._send_measurement()
                next_t += period
                dt_ = next_t - time.perf_counter()
                if dt_ > 0:
                    time.sleep(dt_)
        self._autosend_thr = threading.Thread(target=run, daemon=True)
        self._autosend_thr.start()

    def _send_line(self, s: str):
        if not self.ser: return
        payload = (s + "\r").encode("ascii", errors="ignore")
        with self._lock:
            self.ser.write(payload)
            self.ser.flush()

    def _now_temp(self) -> float:
        t = time.perf_counter()
        dt_min = (t - self._last_temp_update) / 60.0
        if abs(self.dev.temp_drift_c_per_min) > 0 and dt_min > 0:
            self.dev.temp_c += self.dev.temp_drift_c_per_min * dt_min
            self._last_temp_update = t
        return self.dev.temp_c

    def _measurement_strings(self) -> Tuple[str, str]:
        t = time.perf_counter()
        p_bar = self.sig.value(t)
        p_unit = convert_from_bar(p_bar, self.dev.unit)
        r = f"{p_unit:.6f}"
        g = f"{p_unit:.6f},{self.dev.unit}"
        if self.dev.addr != 0 and self.dev.echo_address_in_reply:
            r = f"{self.dev.addr}:{r}"
            g = f"{self.dev.addr}:{g}"
        return r, g

    def _send_measurement(self):
        _, g = self._measurement_strings()
        self._send_line(g)

    def handle_command(self, raw: str):
        if not raw:
            return
        line = raw.strip()
        if self.dev.addr != 0:
            m = re.match(r"^(\d{1,2}):(.*)$", line)
            if m:
                addr = int(m.group(1))
                if addr != self.dev.addr:
                    return
                line = m.group(2).strip()

        if line == "I":
            self._send_line(IDENTITY)
            return

        if line.startswith("N,"):
            try:
                addr = int(line.split(",",1)[1])
                self.dev.addr = addr
                self._send_line(f"N,{addr}")
            except Exception:
                self._send_line("ERR")
            return

        if line.startswith("U,"):
            unit = line.split(",",1)[1].strip()
            if unit in UNITS_ALLOWED:
                self.dev.unit = unit
                self._send_line(f"U,{unit}")
            else:
                self._send_line("ERR")
            return

        if line.startswith("A,"):
            v = line.split(",",1)[1].strip()
            if v == "0":
                self.dev.autosend = False
                self._stop.set()
                self._send_line("A,0")
            elif v == "1":
                self.dev.autosend = True
                self._stop.clear()
                self._send_line("A,1")
                if not (self._autosend_thr and self._autosend_thr.is_alive()):
                    self._start_autosend()
            else:
                self._send_line("ERR")
            return

        if line == "R":
            r, _ = self._measurement_strings()
            self._send_line(r)
            return

        if line == "*G":
            _, g = self._measurement_strings()
            self._send_line(g)
            return

        if line == "*T":
            tC = self._now_temp()
            s = f"{tC:.2f},C"
            if self.dev.addr != 0 and self.dev.echo_address_in_reply:
                s = f"{self.dev.addr}:{s}"
            self._send_line(s)
            return

        if line == "*Z":
            t = time.perf_counter()
            f = 32000.0 + 500.0*math.sin(2*math.pi*0.01*(t))
            dv = 450.0 + 5.0*math.sin(2*math.pi*0.005*(t))
            s = f"{f:.1f},{dv:.1f}"
            if self.dev.addr != 0 and self.dev.echo_address_in_reply:
                s = f"{self.dev.addr}:{s}"
            self._send_line(s)
            return

        if line.startswith("S,"):
            try:
                body = line.split(",", 1)[1]
                k, v = body.split(",", 1)
                k = k.strip().upper()
                v = v.strip()
                if k == "P2":
                    self.sig.step_to(float(v))
                    self._send_line(f"S,OK,P2,{v}")
                    return
                elif k == "TAU":
                    self.sig.cfg.tau_s = max(1e-6, float(v))
                    self._send_line(f"S,OK,TAU,{self.sig.cfg.tau_s}")
                    return
                elif k == "MODE":
                    vm = v.lower()
                    if vm in {"settle","sine","saw","noise","const"}:
                        self.sig.cfg.mode = vm
                        self.sig.t0 = time.perf_counter()
                        self._send_line(f"S,OK,MODE,{vm}")
                        return
                    else:
                        self._send_line("S,ERR,BAD_MODE")
                        return
                else:
                    self._send_line("S,ERR,BAD_KEY")
                    return
            except Exception:
                self._send_line("S,ERR")
                return

        self._send_line("ERR")

    def serve(self):
        assert self.ser is not None
        buf = b""
        try:
            while True:
                chunk = self.ser.read(256)
                if chunk:
                    buf += chunk
                    while b"\r" in buf or b"\n" in buf:
                        for sep in (b"\r", b"\n"):
                            idx = buf.find(sep)
                            if idx != -1:
                                line = buf[:idx].decode(errors="ignore")
                                buf = buf[idx+1:]
                                if line.strip():
                                    self.handle_command(line)
                                break
                else:
                    time.sleep(0.01)
        except KeyboardInterrupt:
            pass

def parse_args():
    p = argparse.ArgumentParser(
        description="RS485 DPS8000-compatible pressure sensor simulator."
    )
    p.add_argument("--port", required=False, default="/dev/ttySIM",
                   help="Serial port for RS-485 device side (sim-portti, esim. /dev/ttySIM)")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--unit", default="bar", choices=sorted(UNITS_ALLOWED))
    p.add_argument("--addr", type=int, default=0)
    p.add_argument("--autosend", action="store_true")
    p.add_argument("--rate", type=float, default=1.0)
    p.add_argument("--temp", type=float, default=25.0)
    p.add_argument("--temp-drift", type=float, default=0.0)
    p.add_argument("--echo-addr", action="store_true")

    p.add_argument("--mode", default="settle",
                   choices=["sine","saw","settle","noise","const"])
    p.add_argument("--offset", type=float, default=1.0)
    p.add_argument("--amplitude", type=float, default=0.2)
    p.add_argument("--freq", type=float, default=0.05)
    p.add_argument("--p1", type=float, default=1.5)
    p.add_argument("--p2", type=float, default=1.0)
    p.add_argument("--tau", type=float, default=30.0)
    p.add_argument("--noise-std", type=float, default=0.01)

    a = p.parse_args()
    dev = DeviceCfg(
        port=a.port, baud=a.baud, unit=a.unit, addr=a.addr,
        autosend=a.autosend, autosend_rate_hz=a.rate,
        temp_c=a.temp, temp_drift_c_per_min=a.temp_drift,
        echo_address_in_reply=a.echo_addr
    )
    sig = SignalCfg(
        mode=a.mode, offset=a.offset, amplitude=a.amplitude, freq_hz=a.freq,
        p1=a.p1, p2=a.p2, tau_s=a.tau, noise_std=a.noise_std
    )
    return dev, sig

def main():
    dev, sig_cfg = parse_args()
    sig = Signal(sig_cfg)
    sim = DPSSim(dev, sig)
    sim.open()
    try:
        print(f"[SIM] RS485 SIM on {dev.port} @ {dev.baud} baud; addr={dev.addr}, unit={dev.unit}, autosend={dev.autosend}")
        print(f"[SIM] Mode={sig_cfg.mode} (p1={sig_cfg.p1}, p2={sig_cfg.p2}, tau={sig_cfg.tau_s}, offset={sig_cfg.offset}, amp={sig_cfg.amplitude})")
        sim.serve()
    finally:
        sim.close()

if __name__ == "__main__":
    sys.exit(main())
