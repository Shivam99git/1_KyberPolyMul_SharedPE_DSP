# Reproducibility Report

Generated: n/a  |  mode: `n/a`  |  arguments: ``

## Environment

- Python None (numpy None, scipy None, matplotlib None), None
- Vivado (local): not found; manuscript results were generated with Vivado 2024.2
- FPGA part: None  |  git commit: None

| # | Stage | Status | Evidence | Seconds |
|--:|---|---|---|--:|

## Functional Verification

**PASS** -- software reference model (NTT model vs independent schoolbook vs stored golden output): 256 vectors, 65,536 coefficients, mismatches = 0.

| Design | tests | coefficients checked | RTL vs schoolbook mismatches | status |
|---|--:|--:|--:|---|
| per_phase_baseline | 256 | 65,536 | 0 | PASS |
| pipelined_barrett | 256 | 65,536 | 0 | PASS |
| shared_pe | 256 | 65,536 | 0 | PASS |

Evidence: `results/json/functional_verification.json`, `results/csv/functional_verification.csv`, RTL outputs `results/sim/*/rtl_out.mem`.

## Barrett Verification

**PASS** -- q=3329, K=24, M=5039: 16,777,216 inputs (min 0, max 16777215), mismatches = 0; largest pre-correction remainder 5713 < 2q = 6658 (one conditional subtraction always suffices).
RTL simulation of both reducers over the same inputs: **PASS** (primary mismatches 0, pipelined 0).

Evidence: `results/json/barrett_verification.json`, `results/logs/sim_barrett.log`.

## Cycle Counts

| Design | wait length c | analytical (Eq. 3) | RTL | difference | status |
|---|--:|--:|--:|--:|---|
| shared_pe | 3 | 27,269 | 27,269 | 0 | PASS |
| per_phase_baseline | 3 | 27,269 | 27,269 | 0 | PASS |
| pipelined_barrett | 4 | 30,853 | 30,853 | 0 | PASS |

Behavioural Python model: 27,269 cycles, 3584 multiplier issues. Trace samples: 27,268.

Evidence: `results/csv/cycle_counts.csv`, `results/json/cycle_summary.json`.

## FPGA Resources

**PASS** (53/53 checks against the manuscript pass) -- evidence: archived raw data (`reports/raw/vivado`), tool: Vivado v.2024.2 (lin64) Build 5239630 Fri Nov 08 22:34:34 MST 2024.

| Design (10 ns, post-route) | LUT | LUT logic | LUT mem | FF | slices | DSP48E1 | BRAM |
|---|--:|--:|--:|--:|--:|--:|--:|
| shared_pe | 907 | 651 | 256 | 357 | 290 | 3 | 0 |
| per_phase_baseline | 1250 | 994 | 256 | 474 | 406 | 12 | 0 |
| pipelined_barrett | 908 | 652 | 256 | 336 | 269 | 3 | 0 |

Evidence: `results/csv/{resource,timing,power,hierarchy}_summary.csv`, `results/json/derived_metrics.json`.

## Timing

**PASS** (45/45 checks against the manuscript pass) -- evidence: archived raw data (`reports/raw/vivado`), tool: Vivado v.2024.2 (lin64) Build 5239630 Fri Nov 08 22:34:34 MST 2024.

| Design | WNS@10 ns | Fmax derived (MHz) | closed period (ns) | Fmax closed (MHz) | cycles | latency (us) |
|---|--:|--:|--:|--:|--:|--:|
| shared_pe | -3.011 | 76.86 | 13.418 | 74.53 | 27,269 | 365.90 |
| per_phase_baseline | -3.409 | 74.58 | 13.798 | 72.47 | 27,269 | 376.26 |
| pipelined_barrett | 0.503 | 105.30 | 8.300 | 120.48 | 30,853 | 256.08 |

Evidence: `results/csv/{resource,timing,power,hierarchy}_summary.csv`, `results/json/derived_metrics.json`.

## Power

**PASS** (14/14 checks against the manuscript pass) -- evidence: archived raw data (`reports/raw/vivado`), tool: Vivado v.2024.2 (lin64) Build 5239630 Fri Nov 08 22:34:34 MST 2024.

| Design (10 ns vectorless) | dynamic (mW) | static (mW) | total (mW) | energy/op (uJ) |
|---|--:|--:|--:|--:|
| shared_pe | 9.084 | 68.421 | 77.505 | 28.36 |
| per_phase_baseline | 11.816 | 68.426 | 80.241 | 30.19 |
| pipelined_barrett | 9.187 | 68.421 | 77.609 | 19.87 |

- saif_manuscript_stimulus: shared-PE 4.796 mW vs per-phase 6.781 mW at 13.798 ns -> -29.3 % (SAIF matched 19 % / 13 % of design nets)

- saif_random_stimulus: shared-PE 5.700 mW vs per-phase 7.952 mW at 13.798 ns -> -28.3 % (SAIF matched 19 % / 13 % of design nets)

- vectorless_common_period: shared-PE 6.489 mW vs per-phase 8.459 mW at 13.798 ns -> -23.3 %

Evidence: `results/csv/{resource,timing,power,hierarchy}_summary.csv`, `results/json/derived_metrics.json`.

## Constant-Time Verification

**PASS** -- No data-dependent variation was observed in execution cycle count or memory-address sequence under the evaluated RTL control-flow model.

| Design | vectors | latency (cycles) | A fixed latency | B control trajectory | C address sequence | negative control (data registers differ) |
|---|--:|--:|---|---|---|---|
| per_phase_baseline | 256 | 27,269 | True | True | True | True |
| pipelined_barrett | 256 | 30,853 | True | True | True | True |
| shared_pe | 256 | 27,269 | True | True | True | True |

Scope: RTL control-flow model. Combinational glitches, routing capacitance and physical measurement effects are outside this experiment; no claim of physical side-channel resistance is made.

Evidence: `results/json/constant_time.json`, `results/csv/constant_time.csv`, `results/logs/sim_constant_time_*.log`.

## TVLA

**WARN** (22/26) -- simulated, register-level Hamming-distance model, fixed-vs-random Welch t-test, threshold |t| > 4.5; evidence: archived raw data (`data/tvla`).

| Experiment | traces/group | samples | evaluated | max abs t | cycles above | expected by chance | null max abs t |
|---|--:|--:|--:|--:|--:|--:|--:|
| main_baseline | 400 | 27,268 | 24,192 | 73.50 | 5511 (22.78 %) | 0.16 | 4.50 |
| main_shared | 400 | 27,268 | 24,192 | 73.50 | 5511 (22.78 %) | 0.16 | 4.50 |
| masked | 400 | 54,536 | 48,384 | 4.52 | 1 (0.00 %) | 0.33 | 4.33 |
| shuffle_off | 400 | 27,268 | 24,192 | 73.26 | 5530 (22.86 %) | 0.16 | 3.85 |
| shuffle_on | 400 | 27,268 | 27,266 | 6.34 | 8 (0.03 %) | 0.19 | 4.09 |

Shared-PE vs per-phase t-traces differ in 6 of 27,268 cycles (0.022 %), largest discrepancy 2.86, FSM states ['S_BM_M1W', 'S_INTT_MULW', 'S_SCALE_MULW'].

- five fixed secrets AS ORIGINALLY RUN (each secret a constant polynomial): max|t| 82.0 - 87.2, 24.3 - 26.7 % of cycles above threshold.

- five independent RANDOM fixed secrets (corrected): max|t| 49.8 - 69.3, 21.8 - 22.3 % of cycles above threshold.

These are pre-silicon simulation results, not physical power measurements.

Evidence: `results/json/tvla_summary.json`, `results/csv/tvla_*.csv`, `results/figures/fig_tvla.pdf`.

## Masking

**PASS** -- model: 250 masked products, failures 0; RTL core(f1,g)+core(f2,g)==core(f,g): PASS (64 vectors, mismatches 0); latency 2.00x.

TVLA of the masked protocol (400 traces/group): max|t| = 4.52, 1 of 48,384 cycles above threshold (chance 0.33), null max|t| 4.33. First-order protection under the evaluated register-level model only; higher-order and glitch-extended leakage are outside this experiment.

Evidence: `results/json/masking_verification.json`, `results/json/tvla_summary.json`.

## Shuffling

**PASS** -- schedule equivalence over 16,384 (start, stride) pairs: 0 differ; model 650 runs, failures 0, cycles unchanged; RTL: PASS (384 runs, mismatches 0, latency 27269); permutation state 64 flip-flops (declared).

TVLA (400 traces/group): matched control max|t| 73.3 (5530 cycles above) -> shuffled max|t| 6.3 (8 of 27,266, chance 0.19). Shuffling is a hiding countermeasure: residual first-order leakage remains and its benefit depends on the trace count.

Evidence: `results/json/shuffling_verification.json`.

## Manuscript Consistency

**PASS** -- 200 PASS, 4 WARN, 0 FAIL, 0 SKIPPED of 204 checks (`data/expected/manuscript_results.json` vs generated).

| Status | Check | Expected | Generated | Note |
|---|---|--:|--:|---|
| WARN | tvla_multi_random_tmin | 82.1 | 49.79534701409773 | DISCREPANCY: the manuscript describes five independent fixed secrets, but the original script built constant-coefficient polynomials; with independent random secrets the range is lower |
| WARN | tvla_multi_random_tmax | 87.2 | 69.34530180953064 | see tvla_multi_random_tmin |
| WARN | tvla_multi_random_pmin | 24.3 | 21.77992724867725 | see tvla_multi_random_tmin |
| WARN | tvla_multi_random_pmax | 26.7 | 22.34209656084656 | see tvla_multi_random_tmin |

Evidence: `results/csv/manuscript_consistency.csv`, `results/json/manuscript_consistency.json`.
