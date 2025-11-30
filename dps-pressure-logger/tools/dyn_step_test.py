#!/usr/bin/env python3
from __future__ import annotations
import argparse, random, time, sys
from pathlib import Path
import serial

from csv_writer import CSVRotateConfig, CSVRotatingWriter

HEADERS = ["ts_iso","t_perf","pressure","unit","source",
           "event","target_p2_bar","tau_s"]

def send(ser: serial.Serial, cmd: str, sleep: float = 0.05) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(sleep)
    resp = ser.readline().decode(errors="ignore").strip()
    return resp

def read_pressure(ser: serial.Serial, retries: int = 2) -> tuple[float, str]:
    last = ""
    for _ in range(retries + 1):
        last = send(ser, "*G", sleep=0.05)
        if last:
            try:
                if "," in last:
                    v, u = last.split(",", 1)
                    return float(v), u
                else:
                    return float(last), ""
            except Exception:
                pass
        time.sleep(0.05)
    raise RuntimeError(f"Bad reply for *G: {last!r}")

def iso_now_local() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()

def main():
    ap = argparse.ArgumentParser(description="Dynamic step test against RS-485 DPS-simulator")
    ap.add_argument("--port", required=False, default="/dev/ttyLOG",
                    help="Reader RS-485 port (logger-portti, esim. /dev/ttyLOG)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--rate", type=float, default=2.0, help="sample rate Hz")
    ap.add_argument("--pmin", type=float, default=0.6, help="random p2 lower bound (bar)")
    ap.add_argument("--pmax", type=float, default=1.8, help="random p2 upper bound (bar)")
    ap.add_argument("--taumin", type=float, default=8.0, help="random tau lower bound (s)")
    ap.add_argument("--taumax", type=float, default=45.0, help="random tau upper bound (s)")
    ap.add_argument("--stepmin", type=float, default=10.0, help="min seconds between steps")
    ap.add_argument("--stepmax", type=float, default=30.0, help="max seconds between steps")
    ap.add_argument("--prefix", default="dyn", help="CSV prefix")
    ap.add_argument("--wdir", type=Path, default=Path.cwd())
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    send(ser, "U,bar"); send(ser, "A,0")

    cfg_csv = CSVRotateConfig(
        prefix=args.prefix,
        dirpath=args.wdir,
        headers=HEADERS,
        flush_every=20,
    )

    period = 1.0 / max(1e-6, args.rate)
    next_sample = time.perf_counter()
    next_step = time.perf_counter() + random.uniform(args.stepmin, args.stepmax)
    current_p2 = None
    current_tau = None

    with CSVRotatingWriter(cfg_csv) as w:
        print("Dynamiikkatesti käynnissä. Lopetus: Ctrl+C")
        while True:
            now = time.perf_counter()
            event = ""

            if now >= next_step:
                target = round(random.uniform(args.pmin, args.pmax), 4)
                tau = round(random.uniform(args.taumin, args.taumax), 3)
                r1 = send(ser, f"S,TAU,{tau}")
                r2 = send(ser, f"S,P2,{target}")
                event = f"STEP p2={target} tau={tau} ({r1}|{r2})"
                current_p2, current_tau = target, tau
                next_step = now + random.uniform(args.stepmin, args.stepmax)

            try:
                p, unit = read_pressure(ser)
                row = {
                    "ts_iso": iso_now_local(),
                    "t_perf": now,
                    "pressure": p,
                    "unit": unit or "bar",
                    "source": "DPS8000_SIM",
                    "event": event,
                    "target_p2_bar": current_p2 if current_p2 is not None else "",
                    "tau_s": current_tau if current_tau is not None else "",
                }
                w.write(row)
            except Exception as e:
                row = {
                    "ts_iso": iso_now_local(),
                    "t_perf": now,
                    "pressure": "",
                    "unit": "bar",
                    "source": f"ERR:{e}",
                    "event": event or "READ_ERR",
                    "target_p2_bar": current_p2 if current_p2 is not None else "",
                    "tau_s": current_tau if current_tau is not None else "",
                }
                w.write(row)

            next_sample += period
            sleep = next_sample - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_sample += int((-sleep)//period + 1) * period

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
