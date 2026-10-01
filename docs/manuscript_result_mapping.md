# Manuscript result mapping

This map connects the reproducibility artifact to the reported evidence. `--from-reports` parses
archived raw evidence and regenerates derived outputs; it does not rerun hardware experiments.
Expected values used for comparison are isolated in `data/expected/manuscript_results.json`.

| Manuscript result | Evidence source | Regeneration / output |
|---|---|---|
| Functional polynomial multiplication | `data/test_vectors/`, `tb/functional/`, archived simulator outputs in `reports/raw/sim/` | `scripts/verification/run_reference_tests.py`; `results/json/functional_verification.json` |
| Barrett reduction | `tb/barrett/`, `scripts/verification/barrett_exhaustive.py` | exhaustive comparison over the declared input range; result under `results/` |
| Cycle counts and phase breakdown | Functional RTL logs/testbench and cycle model | `scripts/verification/cycle_model.py`; `results/csv/cycle_counts.csv` |
| Constant-time control and addresses | `tb/constant_time/`, archived traces/logs | `scripts/verification/ct_report.py`; `results/csv/constant_time.csv` |
| FPGA resource utilization | `reports/raw/vivado/` | report parser; `results/csv/resource_summary.csv` |
| Timing, Fmax, and latency | `reports/raw/vivado/` plus cycle counts | timing parser and metric derivation; `results/csv/timing_summary.csv` |
| Power estimates | Vivado power reports and archived SAIF evidence in `reports/raw/vivado/` | power parser/analysis; `results/csv/power_summary.csv` |
| Simulated TVLA | `data/tvla/` raw moments and deterministic seeds in scripts | `scripts/tvla/analyze_tvla.py`; `results/json/tvla_summary.json` |
| Masking experiment | RTL and model outputs; raw TVLA moments | `scripts/masking/run_masking_check.py`; `results/json/masking_verification.json` |
| Shuffling experiment | RTL and model outputs; raw TVLA moments | `scripts/shuffling/run_shuffling_check.py`; `results/json/shuffling_verification.json` |
| Derived manuscript tables and figures | Parsed/derived `results/` CSV/JSON | `scripts/reporting/` and `scripts/figures/`; `manuscript_artifacts/` |

The reproducibility report records which evidence was regenerated and which was archived. The
consistency checker reports discrepancies without changing either measured values or expected
manuscript values. Published comparisons to prior work are literature values and are not generated
by this repository.
