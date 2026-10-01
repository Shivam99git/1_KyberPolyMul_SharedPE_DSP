# Verification

Every experiment below is run by `./reproduce_all.sh` and writes a machine-readable result under
`results/`. "RTL" means the Verilog in `rtl/` simulated with the Vivado Simulator (xsim, Vivado
2024.2); "software" means the Python/numpy scripts, which need no proprietary tool.

## 1. Reference model and test vectors

| Item | Where |
|---|---|
| Golden model (NTT, INTT, base multiplication, brute-force schoolbook) | `scripts/common/kyber_ref.py` |
| Vector generator, `--check` mode regenerates every file from its seed and compares byte-for-byte | `scripts/verification/gen_test_vectors.py` |
| 256 vectors: 16 directed corner cases + 240 random pairs | `data/test_vectors/multi_{f,g,h}.mem` |
| Directed corner cases | zero·r, r·zero, 1·r, r·1, (q−1)·r, all-(q−1)², (q−1)·ones, ones·ones, x·r, x²⁵⁵·x = −1, x²⁰⁰·x¹⁰⁰ = −x⁴⁴, (q−1)² in coefficient 0, ramp·ramp, r², (q−1)·r, x¹²⁸·x¹²⁸ |
| Seeds | random pairs 777, corner polynomial `r` 999, directed example 42, mask polynomials 0x4D41534B |

The expected product stored in `multi_h.mem` is the NTT-based model's output, **cross-checked
against schoolbook multiplication before it is written**. `run_reference_tests.py` additionally:

1. checks the constants (ζ = 17 primitive 256th root, N_INV = 3303, Barrett K = 24, M = 5039);
2. checks four hand-derived identities (1·g = g, 0·g = 0, x²⁰⁰·x¹⁰⁰ = −x⁴⁴, x²⁵⁵·x = −1);
3. recomputes **all 256 products with a separate schoolbook implementation** (numpy convolution
   folded modulo x²⁵⁶ + 1; it shares no code with the NTT model) and compares NTT model,
   stored `multi_h.mem` and schoolbook.

## 2. RTL against the independent reference

`tb/functional/tb_polymul_functional.v` runs all 256 vectors through the selected core
(`ntt_core_shared`, `ntt_core_baseline`, or `ntt_core_shared` + `USE_PIPELINED_BARRETT`), resets
the core between vectors, loads both operand memories, pulses `start`, waits for `done`, and reads
back the 256 result words. The words are compared with `multi_h.mem` **and** written to
`results/sim/<design>/rtl_out.mem`; `run_reference_tests.py` then compares those words with the
schoolbook product recomputed from f and g, so the verdict does not depend on the testbench's own
comparison or on `multi_h.mem`.

Reported per design: number of complete polynomial multiplications (256), output coefficients
checked (65 536), mismatches, PASS/FAIL (`results/json/functional_verification.json`).

## 3. Barrett reduction

`scripts/verification/barrett_exhaustive.py` evaluates the reducer (with the RTL's bit widths) for
**every** 24-bit input (2²⁴ = 16 777 216) and compares with the exact `x mod 3329`. It reports
tested inputs, mismatches, minimum and maximum input, the largest pre-correction remainder
(5713 < 2q, so a single conditional subtraction is always enough) and checks that the constants in
`rtl/common/kyber_params.vh` equal the derived ones. `tb/barrett/tb_barrett_exhaustive.v` repeats
the same exhaustive comparison on the **RTL** `mod_reduce_barrett` and on the two pipelined stages
`mod_reduce_barrett_stage1/2`. The multiplier only feeds the reducer with 0 … (q−1)² = 11 075 584,
a strict subset of the range tested.

## 4. Cycle counts

**Definition.** Latency = number of clock edges after the edge that samples `start`, up to and
including the edge at which `done` is registered high. All stimulus is driven 1 ns after a clock
edge, so there is no start-edge race. This equals the closed-form N_cyc of
`docs/architecture.md` (the FSM spends exactly one clock in each of `S_NTT_INIT` … `S_DONE`;
`S_IDLE` is not counted).

The testbench splits vector 0's latency by FSM phase (using `dut.state`) and counts multiplier
issues (`dut.mult_start`). `scripts/verification/cycle_model.py` evaluates Eq. (3) independently
(runs × states + waits × (c − 1)) and requires **difference = 0** for every phase and total:

| Design | c | analytical | RTL | difference |
|---|--:|--:|--:|--:|
| primary shared-PE | 3 | 27 269 | 27 269 | 0 |
| per-phase reference | 3 | 27 269 | 27 269 | 0 |
| pipelined Barrett | 4 | 30 853 | 30 853 | 0 |

(`results/csv/cycle_counts.csv`; the table is regenerated, not typed.) A third, behavioural
estimate comes from the Python power model, which reaches `S_DONE` after 27 268 cycles (+1 for
the `S_DONE` cycle) and issues the multiplier 3 584 times.

**Why 27 268 transition samples for a 27 269-cycle run.** The power-proxy trace has one
Hamming-distance sample per clock edge from the first edge after the start-capturing edge up to the
edge that enters `S_DONE`: 27 268 consecutive samples (the first is taken against the pre-launch
reset snapshot). The `S_DONE` cycle — the 27 269th — only raises the 1-bit `done` flag, whose
toggle is input independent, and is not sampled.

## 5. Control-flow and memory-address invariance

`tb/constant_time/tb_constant_time.v` records, for every clock edge of the run window, three
fingerprints and compares each live, cycle by cycle, with vector 0 (the all-zero corner, chosen as
an adversarial reference), plus a 64-bit FNV-style hash per stream for the report:

| | Compared every cycle | Signals |
|---|---|---|
| **A** fixed execution latency | length | cycles from `start` to `done` |
| **B** invariant FSM/control trajectory | control word | FSM state, `target_sel`, `layer`, `len_reg`, `start_reg`, `j_reg`, `k_idx`, `bm_i`, `scale_idx`, `mult_start`, `mult_done`, `done` |
| **C** invariant memory-address sequence | address word | both read-address pairs (`a_ra0/1`, `b_ra0/1`), both write enables, both write addresses (masked to 0 when the enable is low: those registers are outside the reset block and carry a don't-care value when no write occurs; `a_ra0` is the testbench-driven external read port in `S_DONE` and is masked there) |
| D negative control | data word | `wa`, `wb`, `w_t`, memory write data — these **must** differ between inputs |

D exists to show the harness is able to see data dependence at all: if D were identical across
inputs the experiment would be vacuous. Results for all 256 vectors on the primary, pipelined and
per-phase cores: A, B and C hold; D differs for 255/255 other vectors
(`results/json/constant_time.json`).

Wording used throughout the repository: *No data-dependent variation was observed in execution
cycle count or memory-address sequence under the evaluated RTL control-flow model.* This is an
RTL-level, zero-delay experiment. Combinational glitches, routing capacitance and physical
measurement effects are outside it, and it says nothing about power or electromagnetic leakage
(`docs/security_evaluation.md`).

## 6. Validation of the power model against the RTL

`tb/power/tb_register_trace.v` dumps every modelled register 1 ns after each clock edge for
vector 5 (35 fields for the shared core, 47 for the per-phase core, 27 269 edges).
`scripts/tvla/validate_model_vs_rtl.py` runs `scripts/tvla/core_model.py` on the same vector and
requires equality of every field at every edge (the memory write address/data registers, which the
RTL does not reset, print `x` until first written and are skipped: 14 364 values). Result:
0 mismatches over 940 051 (shared) and 1 267 279 (per-phase) compared values.

## 7. Masking and shuffling correctness

* Masking (`scripts/masking/run_masking_check.py`, `tb/functional/tb_masking.v`): the model checks
  250 masked products (50 operand pairs × 5 masks) against schoolbook; the RTL runs the **unmodified**
  `ntt_core_shared` three times per vector (on (f1,g), (f2,g) and (f,g)) for all 256 vectors and
  requires core(f1,g) + core(f2,g) mod q = core(f,g) = golden product.
* Shuffling (`scripts/shuffling/run_shuffling_check.py`, `tb/functional/tb_shuffled.v`): the visited
  (layer, j, k) set equals the original schedule for every one of the 16 384 (start, stride)
  pairs (both transforms), the permutation is a bijection for every pair of the 128- and 256-item
  lists, and each work item lands in each time slot equally often. The model (650 runs) and the
  RTL (6 LFSR seeds × 256 vectors = 1 536 runs) give the correct product, a latency of 27 269 and
  3 584 multiplier issues for every seed; the address trace is data independent for a fixed seed
  and differs between seeds.

## 8. What is not verified here

* No physical measurement of any kind (power, EM, timing) exists in this repository.
* The Python power model is a register-level Hamming-distance proxy; glitching, routing
  capacitance and noise are not modelled.
* Vivado numbers are specific to Vivado 2024.2 and the `xc7a35tcpg236-1` model; other releases may
  differ (`docs/reproducibility.md`).
* Table VII of the manuscript quotes other authors' published results; they are not regenerated.
