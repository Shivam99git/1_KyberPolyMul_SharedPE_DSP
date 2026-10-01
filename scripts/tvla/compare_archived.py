#!/usr/bin/env python3
"""Check that freshly generated TVLA raw moments are bit-identical to the archived ones.

    python3 scripts/tvla/compare_archived.py [--fresh-dir results/tvla_raw] [--archived-dir data/tvla]

Every experiment present in the fresh directory is compared, array by array, with the file of the
same name in the archive. The TVLA runs are fully seeded and use exact integer accumulation, so
any difference indicates a change in the model, the seeds or the Python/numpy environment.
Writes results/json/tvla_determinism.json; exit 1 on a difference, 3 if nothing to compare.
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh-dir", default=repo.TVLA_GEN)
    ap.add_argument("--archived-dir", default=repo.TVLA_RAW)
    a = ap.parse_args()
    res, bad = {}, 0
    for f in sorted(os.listdir(a.fresh_dir)) if os.path.isdir(a.fresh_dir) else []:
        if not f.endswith(".npz"):
            continue
        arch = os.path.join(a.archived_dir, f)
        if not os.path.exists(arch):
            res[f] = "no archived counterpart"
            continue
        x, y = np.load(os.path.join(a.fresh_dir, f)), np.load(arch)
        same = sorted(x.files) == sorted(y.files) and all(np.array_equal(x[k], y[k]) for k in x.files)
        res[f] = "identical" if same else "DIFFERENT"
        bad += not same
        print(f"[{'PASS' if same else 'FAIL'}] {f}: {'bit-identical to archived raw moments' if same else 'differs from archived raw moments'}")
    repo.write_json(os.path.join(repo.JSON_DIR, "tvla_determinism.json"), {"files": res, "status": "FAIL" if bad else ("PASS" if res else "SKIPPED")})
    sys.exit(1 if bad else (0 if res else 3))


if __name__ == "__main__":
    main()
