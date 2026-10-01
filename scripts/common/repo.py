"""Shared helpers: repository root, output locations, JSON/CSV writers, metadata.

All scripts locate the repository from their own file location, so they work from
any current directory and never contain machine-specific paths.
"""
import csv
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "data")
VECTORS = os.path.join(DATA, "test_vectors")
EXPECTED = os.path.join(DATA, "expected", "manuscript_results.json")
RESULTS = os.path.join(ROOT, "results")
CSV_DIR = os.path.join(RESULTS, "csv")
JSON_DIR = os.path.join(RESULTS, "json")
TABLE_DIR = os.path.join(RESULTS, "tables")
FIG_DIR = os.path.join(RESULTS, "figures")
LOG_DIR = os.path.join(RESULTS, "logs")
SIM_DIR = os.path.join(RESULTS, "sim")
REPORTS_RAW = os.path.join(ROOT, "reports", "raw", "vivado")      # archived reports of the manuscript runs
REPORTS_GEN = os.path.join(ROOT, "reports", "generated", "vivado")  # written by the Vivado flows
SIM_RAW = os.path.join(ROOT, "reports", "raw", "sim")              # archived simulator logs / RTL outputs
TVLA_RAW = os.path.join(DATA, "tvla")                               # archived raw TVLA moments
TVLA_GEN = os.path.join(RESULTS, "tvla_raw")                        # moments written by run_tvla.py

MANUSCRIPT_VIVADO = "2024.2"
FPGA_PART = "xc7a35tcpg236-1"


def ensure(*dirs):
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def write_json(path, obj):
    ensure(os.path.dirname(path))
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def read_json(path):
    with open(path) as fh:
        return json.load(fh)


def write_csv(path, header, rows):
    ensure(os.path.dirname(path))
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def rel(path):
    """Repository-relative path for display (never prints machine-specific prefixes)."""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def git_commit():
    try:
        out = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unavailable (not a git checkout)"


def tool_version(cmd, pattern=None):
    if shutil.which(cmd[0]) is None:
        return "not found"
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0] if text else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def environment():
    return {
        "python": platform.python_version(),
        "platform": platform.system() + " " + platform.machine(),
        "vivado": tool_version(["vivado", "-version"]),
        "xsim": "available" if shutil.which("xsim") else "not found",
        "fpga_part": FPGA_PART,
        "git_commit": git_commit(),
    }


def fmt_int(x):
    return f"{int(x):,}"


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)
