# Resource-Shared Single-PE NTT Polynomial Multiplier for CRYSTALS-Kyber

This repository is the reproducibility artifact of the manuscript *Constant-Time BRAM-Free
Single-PE Number Theoretic Transform (NTT)-based Polynomial Multiplier for CRYSTALS-Kyber on FPGA*.
It contains the Verilog of a polynomial multiplier for the ring Z_3329[x]/(x^256 + 1) used by
CRYSTALS-Kyber / ML-KEM, in which a single processing element (one modular multiplier, one modular
adder, one modular subtractor) is time-multiplexed across the whole computation, together with a
per-phase reference core, a pipelined-Barrett variant, the testbenches, the Vivado flows, the
leakage-simulation code and the scripts that regenerate every table, figure and number of the
manuscript that is computed from project data. It implements the polynomial-multiplication datapath
only (no hashing, sampling, encoding or key-encapsulation logic).

## Architecture

A complete polynomial multiplication consists of five sequential steps:

1. forward NTT of the first polynomial,
2. forward NTT of the second polynomial,
3. base (pointwise) multiplication,
4. inverse NTT,
5. coefficient scaling.

The steps do not overlap in time, so the core reuses **one modular multiplier, one modular adder
and one modular subtractor** for all of them under FSM control (operand multiplexers select the
inputs). The two 256 × 12-bit coefficient arrays are distributed LUT RAM with asynchronous reads;
the implemented configuration uses **0 BRAM**. One product takes 27 269 clock cycles (30 853 with
the pipelined-Barrett multiplier). Details: [docs/architecture.md](docs/architecture.md); the
per-phase reference used for the comparison: [docs/baseline_definition.md](docs/baseline_definition.md).

Top modules: `ntt_core_shared` ([rtl/shared_pe/ntt_core_shared.v](rtl/shared_pe/ntt_core_shared.v);
compile with `USE_PIPELINED_BARRETT` for the pipelined core), `ntt_core_baseline`
([rtl/per_phase_baseline/ntt_core_baseline.v](rtl/per_phase_baseline/ntt_core_baseline.v)).

## Repository Structure

| Path | Content |
|---|---|
| `rtl/common/` | parameters, Barrett reduction, modular add/sub, multiplier, twiddle ROM |
| `rtl/shared_pe/` | primary core `ntt_core_shared`, shuffled-order variant |
| `rtl/per_phase_baseline/` | per-phase reference core |
| `rtl/pipelined_barrett/` | split Barrett reduction and 3-cycle multiplier |
| `tb/` | testbenches: `functional/`, `constant_time/`, `barrett/`, `power/` (register traces) |
| `scripts/verification/` | vector generation, reference tests, Barrett, cycle model, RTL simulation driver |
| `scripts/synthesis/`, `scripts/implementation/` | non-interactive Vivado flows (`run_shared_pe.tcl`, `run_baseline.tcl`, `run_pipelined.tcl`) |
| `scripts/power/`, `scripts/timing/` | SAIF power runs, latency calculation |
| `scripts/tvla/`, `scripts/masking/`, `scripts/shuffling/` | leakage simulation, masking and shuffling checks |
| `scripts/reporting/`, `scripts/figures/` | report parsing, derived metrics, tables, figures, consistency checker |
| `constraints/` | clock constraint |
| `data/test_vectors/` | test vectors and twiddle images (regenerable from seeds) |
| `data/tvla/` | archived raw TVLA data (per-cycle first/second moments) |
| `data/expected/` | the manuscript's numbers, kept separate from generated results |
| `reports/raw/` | archived Vivado 2024.2 reports and simulator logs of the manuscript runs |
| `reports/generated/` | output of your own Vivado runs (git-ignored) |
| `results/` | generated CSV/JSON/tables/figures/logs and `REPRODUCIBILITY_REPORT.md` |
| `docs/` | architecture, verification, reproducibility, security evaluation, result mapping, baseline |
| `manuscript_artifacts/` | regenerated manuscript tables and figures under the manuscript's labels |

## Hardware Platform

* FPGA: Xilinx Artix-7 **xc7a35t** (`xc7a35tcpg236-1`), out-of-context implementation of the core
  as a standalone block (no I/O buffers).
* Tool: **Vivado 2024.2** (synthesis, implementation, power, Vivado Simulator xsim). The scripts warn
  when another release is detected; other releases may give different numbers.
* Software: Python ≥ 3.8 with numpy, scipy, matplotlib ([requirements.txt](requirements.txt)); bash.
  No other simulator is used. Tested on Ubuntu 24.04 with Python 3.12.

## Quick Start

```bash
git clone <repository-url>
cd <repository>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
source <Vivado-install-dir>/2024.2/settings64.sh      # makes vivado / xvlog / xsim available
./reproduce_all.sh --quick
```

`--quick` runs the RTL simulations (all 256 vectors on three cores, the exhaustive Barrett test,
the control-trace comparison, shuffling and masking), the software reference checks, and the
analyses, regenerates every table and figure and checks the result against the manuscript's values.
It does not run Vivado place-and-route (the FPGA numbers are parsed from the archived raw
reports) and re-analyses archived TVLA data after regenerating one TVLA experiment as a
determinism check. Roughly 6 minutes on the validation environment (TVLA trace generation dominates).

All options of the single entry point:

| Command | Meaning |
|---|---|
| `./reproduce_all.sh` | `--full` if Vivado is found, otherwise `--from-reports` |
| `./reproduce_all.sh --quick` | simulations + software analyses; no Vivado implementation |
| `./reproduce_all.sh --full` | everything: Vivado synthesis/implementation/power, all TVLA runs |
| `./reproduce_all.sh --from-reports` | no Vivado/xsim needed; re-analyse the archived evidence |
| `./reproduce_all.sh --clean` | remove generated outputs only |

## Full Reproduction

```bash
./reproduce_all.sh --full
```

Needs Vivado 2024.2 (a free WebPACK/Standard licence covers the xc7a35t). It synthesizes, places
and routes the three cores and their closure searches (about 16 implementation runs), runs the
SAIF power experiment and regenerates all TVLA data. Roughly 45 minutes with the three flows run
one after another (`--parallel-vivado` runs them concurrently), most of it Vivado. Individual
commands for each part are in [docs/reproducibility.md](docs/reproducibility.md).

## Reproduction From Archived Reports

```bash
./reproduce_all.sh --from-reports
```

For reviewers without Vivado. It parses the checked-in Vivado reports (`reports/raw/vivado/`),
re-parses the archived simulator logs and RTL outputs (`reports/raw/sim/`), re-analyses the
archived raw TVLA data (`data/tvla/`), recomputes every derived quantity and percentage, regenerates
the tables and figures and runs the consistency checker. About three minutes on the validation environment. The report states, per
stage, whether its evidence was regenerated or archived.

## Functional Verification

The reference is an independent Python model of `h = INTT(NTT(f) ∘ NTT(g))` that is itself checked
against brute-force schoolbook multiplication modulo x^256 + 1, over 256 vectors (16 directed
corner cases and 240 random pairs; 65 536 output coefficients). The RTL output is compared with a
schoolbook product recomputed from the operands, not only with the stored golden file. Result:
256 tests, 65 536 coefficients, 0 mismatches for the primary, per-phase and pipelined cores.
The Barrett reducer (q = 3329, K = 24, M = 5039) is checked against `x mod q` for all 2^24 inputs,
in software and on the RTL. See [docs/verification.md](docs/verification.md).

```bash
python3 scripts/verification/run_reference_tests.py        # software reference (+ RTL outputs if simulated)
python3 scripts/verification/run_rtl_sim.py                # all RTL simulations (needs xsim)
python3 scripts/verification/barrett_exhaustive.py         # 2^24 inputs
python3 scripts/verification/cycle_model.py                # Eq. (3) vs RTL cycle counts
```

The cycle count is measured in RTL simulation as the number of clock edges from the edge that
samples `start` to the edge that registers `done`, and compared with the closed-form model; the
difference is required to be 0.

## Synthesis and Implementation

```bash
mkdir -p build/vivado && cd build/vivado
vivado -mode batch -nojournal -nolog -source ../../scripts/synthesis/run_shared_pe.tcl
vivado -mode batch -nojournal -nolog -source ../../scripts/synthesis/run_baseline.tcl
vivado -mode batch -nojournal -nolog -source ../../scripts/synthesis/run_pipelined.tcl
cd ../..
python3 scripts/reporting/extract_results.py --reports-dir reports/generated/vivado
python3 scripts/reporting/derive_metrics.py
```

Each flow is a non-interactive Tcl script (in-memory project, `synth_design -mode out_of_context`,
`opt_design`, `place_design`, `route_design`) that writes utilization (flat and hierarchical),
timing summary, worst paths, route status, clock utilization and power (text and XML) into
`reports/generated/vivado/<design>/`. A closure search finds each core's closed period. **Fmax** =
1000 / (smallest period that meets timing, WNS ≥ 0); a second, "derived" Fmax extrapolates from the
failing 10 ns run as 1000 / (10 − WNS). **Latency** = cycles / frequency (unrounded). **Power** is
Vivado's post-route vectorless estimate at the common 10 ns target (confidence "Medium"), computed
from the per-rail supply currents; an additional SAIF-annotated comparison is provided
(`scripts/power/run_power.py`). Parsing is done by regular expressions over the report files
(`scripts/reporting/vivado_parse.py`); no number is typed in.

## Constant-Time Verification

For every one of the 256 vectors the testbench compares, at every clock edge, (A) the latency,
(B) the control word (FSM state, loop counters, pass selector, multiplier start/done handshake) and
(C) the memory addresses and write enables with those of vector 0. All three are identical on the
primary, pipelined and per-phase cores; a negative control confirms that the data-carrying
registers do differ. *No data-dependent variation was observed in execution cycle count or
memory-address sequence under the evaluated RTL control-flow model.* This is an RTL-level
experiment: combinational glitches, routing capacitance and physical measurement effects are
outside it, and fixed control/address behavior is **not** a claim of physical side-channel
resistance.

## Simulated Leakage Evaluation

A cycle-accurate Python model of the RTL (validated register-for-register against RTL simulation)
yields a per-clock-cycle Hamming-distance power proxy over every register the RTL declares
(35 register fields for the shared core, 47 for the per-phase core). Fixed-versus-random TVLA with
Welch's t-test, 400 traces per group, threshold |t| > 4.5, a random-vs-random null, fixed secret
seed 20260922 and per-group seeds 1001/2002/3003/4004. The unprotected cores show max |t| = 73.5
with 5 511 of 24 192 evaluated cycles (22.8 %) above threshold; the shared-PE and per-phase
traces differ in 6 of 27 268 cycles. A 27 269-cycle run gives 27 268 transition samples because the
trace covers the clock edges up to the entry into `S_DONE`; the `S_DONE` cycle only raises the done
flag. These are **pre-silicon simulation results, not physical power measurements.**
See [docs/security_evaluation.md](docs/security_evaluation.md).

```bash
python3 scripts/tvla/run_tvla.py --out-dir results/tvla_raw        # raw data (about 7 min on 18 cores)
python3 scripts/tvla/analyze_tvla.py --moments-dir results/tvla_raw
```

## Masking and Shuffling

*Additive masking* uses the linearity of the product in one operand: with f = f₁ + f₂ (mod q) the
**unmodified** core is run on (f₁, g) and (f₂, g) and the two results are added outside the core.
The scripts verify core(f₁,g) + core(f₂,g) = core(f,g) in the model and on the RTL and repeat the
TVLA on the two-run protocol (max |t| = 4.52, 1 of 48 384 evaluated cycles above threshold,
0.33 expected by chance; latency 2.00×). This is first-order protection under the evaluated
register-level model only; higher-order and glitch-extended leakage are outside the experiment, and
only the split operand is protected.

*Shuffled issue order* replaces the address incrementers by the affine permutation
p_{i+1} = (p_i + stride) mod L with odd stride (L = number of schedulable work items: 128 per
layer and for base multiplication, 256 for scaling), driven by a 32-bit LFSR. It keeps the product,
the 27 269-cycle latency and the 3 584 multiplier issues, costs 64 declared flip-flops, and in the
model lowers max |t| from 73.3 to 6.3 (8 of 27 266 cycles above threshold, 0.19 expected). It is a
hiding countermeasure: residual first-order leakage remains, its benefit depends on the trace count,
and the seed must be unpredictable.

```bash
python3 scripts/masking/run_masking_check.py
python3 scripts/shuffling/run_shuffling_check.py
```

## Reproducing Manuscript Tables and Figures

| Output | Path |
|---|---|
| Table III (cycles per phase), IV (verification), V (vs per-phase), VI (pipelined), VIII (attribution), countermeasure table | `results/tables/table_{cycles,verification,resources,pipelined,hierarchy,security}.{csv,tex}` |
| Fig. 10(a,b), 11(a,b), 12, TVLA figure, countermeasure traces | `results/figures/fig_{cycle_breakdown,area_breakdown,critical_path,power,slack_distribution,tvla,countermeasures}.{pdf,png}` |
| both of the above under the manuscript's labels | `manuscript_artifacts/` |
| numerical results behind them | `results/csv/*.csv`, `results/json/*.json` |
| everything in one place | `results/REPRODUCIBILITY_REPORT.md` |

```bash
python3 scripts/reporting/format_tables.py
python3 scripts/figures/make_figures.py
```

Block diagrams, FSM drawings and algorithm figures are not data plots and are not regenerated.
Table VII compares against other authors' published numbers and is not regenerated.

## Expected Results

Values below are the verified results of this repository's reference run (Vivado 2024.2); the same
numbers are stored in `data/expected/manuscript_results.json` and checked by
`scripts/reporting/check_manuscript_results.py`.

| Metric | Shared PE | Pipelined | Per-phase reference |
|---|--:|--:|--:|
| LUTs (10 ns, post-route) | 907 | 908 | 1250 |
| FFs | 357 | 336 | 474 |
| DSP48E1 | 3 | 3 | 12 |
| BRAM | 0 | 0 | 0 |
| Cycles / product | 27 269 | 30 853 | 27 269 |
| Closed period | 13.418 ns | 8.300 ns | 13.798 ns |
| Fmax (closed) | 74.5 MHz | 120.5 MHz | 72.5 MHz |
| Latency | 365.9 µs | 256.1 µs | 376.3 µs |
| Dynamic power (vectorless, 10 ns) | 9.08 mW | 9.19 mW | 11.82 mW |

Shared-PE versus per-phase reference: DSP −75.0 %, LUT −27.4 %, occupied slices −28.6 %, dynamic
power −23.1 %, LUT·latency product −29.4 %, same cycle count. Pipelined versus primary: clock
period −38.1 % (1.62× Fmax), cycles +13.1 %, latency −30.0 %.

## Manuscript Result Traceability

[docs/manuscript_result_mapping.md](docs/manuscript_result_mapping.md) maps every quantitative claim
of the manuscript to its configuration, reproduction command, raw evidence and generated result.

## Reproducibility Notes

* **Vivado version.** All archived reports are from Vivado v2024.2 (build 5239630). A different
  release can change synthesis and placement; the checker then reports tool-sensitive differences as
  WARN and the report says so. Regenerated reports reproduce the archived ones exactly with the same
  release (`results/json/report_determinism.json`).
* **Place-and-route variation.** Each number is one deterministic run with default settings; it is
  not a distribution over placement seeds. Timing-closure results (the 13.418, 13.798 and 8.300 ns
  periods) are specific to the tool release and the search procedure.
* **Random seeds.** Every randomized experiment is seeded and the seeds are recorded in the logs and
  in `results/reproduction_metadata.json`. TVLA moments are accumulated with exact integers per
  independent group, so they are bit-identical for any number of worker processes.
* **Checked-in raw data.** `reports/raw/` (Vivado reports with host name and paths removed),
  `data/tvla/` (raw TVLA moments), `data/test_vectors/` (regenerable byte-for-byte).
* **Known discrepancies** between generated results and manuscript text are listed in
  `PUBLIC_RELEASE_AUDIT.md` and flagged WARN by the checker.
* **Platform.** Linux with bash; Vivado and xsim are required only for `--quick`/`--full`.

## Citation

See [CITATION.cff](CITATION.cff).

## License

MIT, see [LICENSE](LICENSE). All RTL, scripts and data in this repository were written for this
work; no third-party RTL or IP cores are included.
