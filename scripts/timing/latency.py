#!/usr/bin/env python3
"""Latency of one polynomial product from clock cycles and clock frequency.

    latency_us = cycles / frequency_hz * 1e6  =  cycles * period_ns / 1000

Used by scripts/reporting/derive_metrics.py with the cycle counts measured in RTL
simulation and the closed clock periods parsed from the Vivado timing reports. The
unrounded frequency is used internally; rounding is applied only when tables are formatted.

    python3 scripts/timing/latency.py --cycles 27269 --period-ns 13.418
    python3 scripts/timing/latency.py --cycles 27269 --freq-mhz 74.5
"""
import argparse


def fmax_mhz(period_ns):
    return 1000.0 / period_ns


def period_ns_from_mhz(freq_mhz):
    return 1000.0 / freq_mhz


def latency_us(cycles, freq_hz):
    return cycles / freq_hz * 1e6


def throughput_per_s(latency_us_value):
    return 1e6 / latency_us_value


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cycles", type=int, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--period-ns", type=float)
    g.add_argument("--freq-mhz", type=float)
    a = ap.parse_args()
    f_hz = (1e9 / a.period_ns) if a.period_ns else a.freq_mhz * 1e6
    lat = latency_us(a.cycles, f_hz)
    print(f"cycles={a.cycles}  frequency={f_hz / 1e6:.6f} MHz  period={1e9 / f_hz:.6f} ns  "
          f"latency={lat:.6f} us  throughput={throughput_per_s(lat):.3f} products/s")


if __name__ == "__main__":
    main()
