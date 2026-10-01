# Reproducibility guide

## Requirements and tool versions

The archived FPGA evidence was produced with Xilinx Vivado 2024.2 for the Artix-7
`xc7a35tcpg236-1`. Re-running implementation requires Vivado with `vivado`, `xvlog`, and
`xsim` available in `PATH`; the open-source software analyses require Python 3 and the packages
listed in `requirements.txt`. The entry point records detected versions and warns when the
Vivado release differs. Do not treat results from another Vivado release as identical.

## Main commands

Run from any directory after cloning:

```sh
./reproduce_all.sh --quick
./reproduce_all.sh --full
./reproduce_all.sh --from-reports
./reproduce_all.sh --clean
```

`--quick` runs the available software analyses and RTL simulations, skipping Vivado synthesis and
implementation. `--full` runs the available experiments and Vivado flows. `--from-reports`
recomputes derived results from checked-in, scrubbed raw reports and archived simulation evidence;
it does not require Vivado. `--clean` removes generated artifacts only. Each stage writes its
command output to `results/logs/`, updates `results/stage_status.tsv`, and contributes to
`results/REPRODUCIBILITY_REPORT.md`. A missing proprietary tool is marked `SKIPPED`.

The implementation flows can be invoked individually with `vivado -mode batch -source
scripts/synthesis/run_shared_pe.tcl`, `scripts/synthesis/run_baseline.tcl`, or
`scripts/synthesis/run_pipelined.tcl` from the repository root. The single top-level script is
recommended because it records status and evidence for all stages in a consistent order.

## Evidence chain

The independent schoolbook reference and deterministic vectors are in `scripts/verification/`
and `data/test_vectors/`. RTL simulations and their archived logs are in `tb/` and
`reports/raw/sim/`. Archived Vivado reports are in `reports/raw/vivado/`; fresh Vivado outputs go
to the ignored `reports/generated/`. Raw register-level TVLA moments are in `data/tvla/`.
Parsers and analyses under `scripts/reporting/`, `scripts/tvla/`, `scripts/timing/`, and
`scripts/figures/` generate the tables, figures, and consistency comparison under `results/` and
`manuscript_artifacts/`.

Expected manuscript values are stored separately in `data/expected/manuscript_results.json`.
Generated metrics are never replaced with expected values. Warnings and discrepancies remain
visible in the report and consistency CSV.
