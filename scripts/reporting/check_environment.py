#!/usr/bin/env python3
"""Report the tool environment and warn about deviations from the manuscript setup.

Required for every mode : Python >= 3.8 with numpy, scipy, matplotlib (requirements.txt)
Optional (full/quick)   : Vivado 2024.2 (vivado, xvlog, xelab, xsim in PATH)
Exit status 1 if a required Python package is missing; tool absence is reported, not fatal.
"""
import importlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402


def main():
    bad = 0
    print(f"Python        : {sys.version.split()[0]}  ({'OK' if sys.version_info >= (3, 8) else 'TOO OLD (need >= 3.8)'})")
    bad += sys.version_info < (3, 8)
    for pkg in ("numpy", "scipy", "matplotlib"):
        try:
            print(f"{pkg:14s}: {importlib.import_module(pkg).__version__}")
        except ImportError:
            print(f"{pkg:14s}: MISSING  (pip install -r requirements.txt)")
            bad += 1
    vv = repo.tool_version(["vivado", "-version"])
    print(f"Vivado        : {vv}")
    for t in ("xvlog", "xelab", "xsim"):
        print(f"{t:14s}: {'found' if shutil.which(t) else 'not found'}")
    print(f"FPGA part     : {repo.FPGA_PART} (Artix-7 xc7a35t)")
    print(f"git commit    : {repo.git_commit()}")
    if vv != "not found" and repo.MANUSCRIPT_VIVADO not in vv:
        print(f"WARNING: Manuscript results were generated with Vivado {repo.MANUSCRIPT_VIVADO}.\n"
              f"         Detected: {vv}. Results may differ because of tool-version changes;\n"
              f"         tool-sensitive differences will be reported as WARN, not as identical reproduction.")
    if vv == "not found":
        print("NOTE: Vivado not found: RTL simulation and FPGA flows cannot run; use --from-reports to verify "
              "the archived evidence, or install Vivado 2024.2 for --quick/--full.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
