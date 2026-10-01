"""Cycle-accurate register-transfer model of the shared-PE core (ntt_core_shared),
the per-phase reference core (ntt_core_baseline) and the shuffled-issue-order
variant (ntt_core_shared_shuffled).

Every register the RTL declares is modelled, so the per-clock Hamming distance
between successive register snapshots is a pre-silicon power proxy. The model is
validated three ways (see scripts/tvla/validate_model_vs_rtl.py and
scripts/verification/run_reference_tests.py):
  * register-for-register against an RTL simulation trace,
  * product bit-exact against schoolbook multiplication,
  * 27,269-cycle schedule and 3,584 multiplier issues.

Core(shared=True,  shuffle=False)  == ntt_core_shared    (35 register fields)
Core(shared=False, shuffle=False)  == ntt_core_baseline  (47 register fields)
Core(shared=True,  shuffle=True)   == ntt_core_shared_shuffled

Shuffled mode models an AFFINE permutation of each phase's independent-work list
(L = number of schedulable work items; L = 128 for every NTT/INTT layer and for
base multiplication, L = 256 for scaling):
    p_i = (start + i*stride) mod L,   stride odd  =>  bijection on [0, L)
driven by a free-running 32-bit LFSR (x^32 + x^30 + x^26 + x^25 + 1).
The five permutation registers (lfsr, p_idx, perm_stride, item_cnt, k_base) are
data independent and are NOT part of the power proxy (see docs/security_evaluation.md).

Address derivation (verified set-equivalent to the original FSM schedule):
    lg     = log2(len)            NTT: lg = 7-layer ; INTT: lg = 1+layer
    gi     = p >> lg              group index
    off    = p & (len-1)          offset inside the group
    j      = (gi << (lg+1)) | off
    k      = k_base +/- gi        NTT: + ; INTT: -
    k_base advances by +/- groups per layer, groups = 128>>lg
With shuffle=False the model reproduces the original incrementing address
generator clock for clock (identical register traces; checked in the test-suite).
"""
import os
Q=3329; K=24; M_BARRETT=(1<<K)//Q; N_INV=3303
_ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),"..",".."))
_d=os.path.join(_ROOT,"data","test_vectors")
ROM_NTT=[int(x,16) for x in open(os.path.join(_d,"zetas_ntt.mem")) if x.strip()]
ROM_BM =[int(x,16) for x in open(os.path.join(_d,"zetas_basemul.mem")) if x.strip()]

def barrett(x):
    t=(x*M_BARRETT)>>K; r0=x-t*Q; return r0-Q if r0>=Q else r0
def mod_add(a,b): s=a+b; return s-Q if s>=Q else s
def mod_sub(a,b): d=a+Q-b; return d-Q if d>=Q else d
def hw(v): return bin(v).count("1")

ST=["S_IDLE","S_NTT_INIT","S_NTT_LOAD","S_NTT_MUL","S_NTT_MULW","S_NTT_WB0","S_NTT_WB1","S_NTT_ADV",
    "S_BM_INIT","S_BM_LOAD","S_BM_M1","S_BM_M1W","S_BM_M2","S_BM_M2W","S_BM_M3","S_BM_M3W","S_BM_WB0",
    "S_BM_M4","S_BM_M4W","S_BM_M5","S_BM_M5W","S_BM_WB1","S_BM_ADV",
    "S_INTT_INIT","S_INTT_LOAD","S_INTT_SUM","S_INTT_MUL","S_INTT_MULW","S_INTT_WB0","S_INTT_WB1","S_INTT_ADV",
    "S_SCALE_INIT","S_SCALE_LOAD","S_SCALE_MUL","S_SCALE_MULW","S_SCALE_WB","S_SCALE_ADV","S_DONE"]
S={n:i for i,n in enumerate(ST)}

class Mult:
    __slots__=("state","prod_r","result","done")
    def __init__(s): s.state=0; s.prod_r=0; s.result=0; s.done=0
    def regs(s): return (s.state,s.prod_r,s.result,s.done)
    def step(s,start,a,b):
        if s.state==0:
            s.done=0
            if start: s.prod_r=a*b; s.state=1
        else:
            s.result=barrett(s.prod_r); s.done=1; s.state=0

class Core:
    def __init__(s, shared=True, shuffle=False, seed=0xACE1_2345):
        s.shared=shared; s.shuffle=shuffle
        s.lfsr = seed & 0xFFFFFFFF or 0x1
        s.mem_a=[0]*256; s.mem_b=[0]*256
        s.state=S["S_IDLE"]; s.done=0; s.target_sel=0
        s.layer=0; s.len_reg=0; s.start_reg=0; s.j_reg=0
        s.k_idx=0; s.bm_i=0; s.scale_idx=0
        s.k_base=0; s.p_idx=0; s.cnt=0; s.stride=1
        s.mult_op_a=0; s.mult_op_b=0; s.mult_start=0
        s.wa=s.wb=s.wc=s.wd=0
        s.w_t=s.w_sum=s.w_diff=0
        s.w_m1=s.w_za1b1=s.w_a0b0=s.w_a0b1=s.w_a1b0=0
        s.mem_a_we=0; s.mem_a_wa=0; s.mem_a_wd=0
        s.mem_b_we=0; s.mem_b_wa=0; s.mem_b_wd=0
        s.mults=[Mult()] if shared else [Mult() for _ in range(4)]
        s.issues=0
    # ---- 32-bit LFSR, x^32+x^30+x^26+x^25+1 ; advances every clock ----
    def _lfsr_step(s):
        fb = ((s.lfsr>>31) ^ (s.lfsr>>29) ^ (s.lfsr>>25) ^ (s.lfsr>>24)) & 1
        s.lfsr = ((s.lfsr<<1) | fb) & 0xFFFFFFFF
    def _draw(s, bits):
        """start,stride for an M=2^bits item list; stride forced odd."""
        if not s.shuffle: return 0, 1
        mask=(1<<bits)-1
        start = s.lfsr & mask
        stride = ((s.lfsr >> bits) & mask) | 1
        return start, stride
    # ---- address derivation, identical to the RTL expressions ----
    def _lg(s, is_intt): return (1+s.layer) if is_intt else (7-s.layer)
    def _derive(s, p, is_intt):
        lg=s._lg(is_intt); L=1<<lg
        gi = p >> lg
        off = p & (L-1)
        j = (gi << (lg+1)) | off
        k = (s.k_base - gi) if is_intt else (s.k_base + gi)
        grp_start = gi << (lg+1)
        return j, k, grp_start
    def _enter_layer(s, is_intt):
        st,sd = s._draw(7)
        s.p_idx=st; s.stride=sd; s.cnt=0
        j,k,gs = s._derive(st, is_intt)
        s.j_reg=j; s.k_idx=k; s.start_reg=gs
    def _adv_layer(s, is_intt):
        s.p_idx = (s.p_idx + s.stride) & 0x7F
        s.cnt += 1
        j,k,gs = s._derive(s.p_idx, is_intt)
        s.j_reg=j; s.k_idx=k; s.start_reg=gs
    # ---- combinational ----
    def _phase(s):
        st=s.state
        return (S["S_NTT_INIT"]<=st<=S["S_NTT_ADV"], S["S_BM_INIT"]<=st<=S["S_BM_ADV"],
                S["S_INTT_INIT"]<=st<=S["S_INTT_ADV"], S["S_SCALE_INIT"]<=st<=S["S_SCALE_ADV"])
    def _reads(s):
        st=s.state; running = st!=S["S_IDLE"] and st!=S["S_DONE"]
        in_bm = S["S_BM_INIT"]<=st<=S["S_BM_ADV"]; in_sc = S["S_SCALE_INIT"]<=st<=S["S_SCALE_ADV"]
        a_ra0 = 0 if not running else ((s.bm_i<<1) if in_bm else (s.scale_idx if in_sc else s.j_reg))
        a_ra1 = (s.bm_i<<1)|1 if in_bm else (s.j_reg+s.len_reg)
        b_ra0 = (s.bm_i<<1) if in_bm else s.j_reg
        b_ra1 = (s.bm_i<<1)|1 if in_bm else (s.j_reg+s.len_reg)
        g=lambda m,i: m[i] if i<256 else 0
        return g(s.mem_a,a_ra0),g(s.mem_a,a_ra1),g(s.mem_b,b_ra0),g(s.mem_b,b_ra1)
    def _addsub(s):
        st=s.state
        if st==S["S_INTT_SUM"]: aa,ab,sa,sb=s.wa,s.wb,s.wb,s.wa
        elif st==S["S_BM_WB0"]: aa,ab,sa,sb=s.w_a0b0,s.w_za1b1,s.wa,s.w_t
        elif st==S["S_BM_WB1"]: aa,ab,sa,sb=s.w_a0b1,s.w_a1b0,s.wa,s.w_t
        else:                   aa,ab,sa,sb=s.wa,s.w_t,s.wa,s.w_t
        return mod_add(aa,ab), mod_sub(sa,sb)
    def _mult_iface(s):
        n,b,i,sc=s._phase()
        if s.shared: return s.mults[0].done, s.mults[0].result
        m = s.mults[0] if n else s.mults[1] if b else s.mults[2] if i else s.mults[3]
        return m.done, m.result
    def regs(s):
        r=[s.state,s.done,s.target_sel,s.layer,s.len_reg,s.start_reg,s.j_reg,s.k_idx,s.bm_i,s.scale_idx,
           s.mult_op_a,s.mult_op_b,s.mult_start,s.wa,s.wb,s.wc,s.wd,s.w_t,s.w_sum,s.w_diff,
           s.w_m1,s.w_za1b1,s.w_a0b0,s.w_a0b1,s.w_a1b0,
           s.mem_a_we,s.mem_a_wa,s.mem_a_wd,s.mem_b_we,s.mem_b_wa,s.mem_b_wd]
        for m in s.mults: r.extend(m.regs())
        return r

    def step(s, start_in=0):
        a_rd0,a_rd1,b_rd0,b_rd1 = s._reads()
        add_y,sub_y = s._addsub()
        mdone,mres = s._mult_iface()
        n_ph,b_ph,i_ph,sc_ph = s._phase()
        if s.shared:
            s.mults[0].step(s.mult_start, s.mult_op_a, s.mult_op_b)
        else:
            for m,g in zip(s.mults,(n_ph,b_ph,i_ph,sc_ph)):
                m.step(s.mult_start and g, s.mult_op_a, s.mult_op_b)
        if s.mem_a_we: s.mem_a[s.mem_a_wa & 0xFF] = s.mem_a_wd
        if s.mem_b_we: s.mem_b[s.mem_b_wa & 0xFF] = s.mem_b_wd
        st=s.state
        s.mult_start=0; s.mem_a_we=0; s.mem_b_we=0
        Z_ntt = ROM_NTT[s.k_idx] if 0 <= s.k_idx < len(ROM_NTT) else 0
        Z_bm  = ROM_BM[s.bm_i]  if 0 <= s.bm_i  < len(ROM_BM)  else 0
        if st==S["S_IDLE"]:
            s.done=0
            if start_in: s.target_sel=0; s.state=S["S_NTT_INIT"]
        elif st==S["S_NTT_INIT"]:
            s.layer=0; s.len_reg=128; s.k_base=0
            s._enter_layer(False)
            s.state=S["S_NTT_LOAD"]
        elif st==S["S_NTT_LOAD"]:
            if not s.target_sel: s.wa,s.wb=a_rd0,a_rd1
            else:                s.wa,s.wb=b_rd0,b_rd1
            s.state=S["S_NTT_MUL"]
        elif st==S["S_NTT_MUL"]:
            s.mult_op_a=Z_ntt; s.mult_op_b=s.wb; s.mult_start=1; s.issues+=1; s.state=S["S_NTT_MULW"]
        elif st==S["S_NTT_MULW"]:
            if mdone: s.w_t=mres; s.state=S["S_NTT_WB0"]
        elif st==S["S_NTT_WB0"]:
            if not s.target_sel: s.mem_a_we=1; s.mem_a_wa=s.j_reg; s.mem_a_wd=add_y
            else:                s.mem_b_we=1; s.mem_b_wa=s.j_reg; s.mem_b_wd=add_y
            s.state=S["S_NTT_WB1"]
        elif st==S["S_NTT_WB1"]:
            if not s.target_sel: s.mem_a_we=1; s.mem_a_wa=s.j_reg+s.len_reg; s.mem_a_wd=sub_y
            else:                s.mem_b_we=1; s.mem_b_wa=s.j_reg+s.len_reg; s.mem_b_wd=sub_y
            s.state=S["S_NTT_ADV"]
        elif st==S["S_NTT_ADV"]:
            if s.cnt != 127:
                s._adv_layer(False); s.state=S["S_NTT_LOAD"]
            else:
                if s.layer==6:
                    if not s.target_sel:
                        s.target_sel=1; s.layer=0; s.len_reg=128; s.k_base=0
                        s._enter_layer(False); s.state=S["S_NTT_LOAD"]
                    else:
                        st2,sd2=s._draw(7); s.p_idx=st2; s.stride=sd2; s.cnt=0
                        s.bm_i=st2; s.state=S["S_BM_INIT"]
                else:
                    s.k_base = s.k_base + (128>>s._lg(False))
                    s.layer+=1; s.len_reg>>=1
                    s._enter_layer(False); s.state=S["S_NTT_LOAD"]
        elif st==S["S_BM_INIT"]:
            st2,sd2=s._draw(7); s.p_idx=st2; s.stride=sd2; s.cnt=0; s.bm_i=st2
            s.state=S["S_BM_LOAD"]
        elif st==S["S_BM_LOAD"]: s.wa,s.wb,s.wc,s.wd=a_rd0,a_rd1,b_rd0,b_rd1; s.state=S["S_BM_M1"]
        elif st==S["S_BM_M1"]:  s.mult_op_a=s.wb; s.mult_op_b=s.wd; s.mult_start=1; s.issues+=1; s.state=S["S_BM_M1W"]
        elif st==S["S_BM_M1W"]:
            if mdone: s.w_m1=mres; s.state=S["S_BM_M2"]
        elif st==S["S_BM_M2"]:  s.mult_op_a=Z_bm; s.mult_op_b=s.w_m1; s.mult_start=1; s.issues+=1; s.state=S["S_BM_M2W"]
        elif st==S["S_BM_M2W"]:
            if mdone: s.w_za1b1=mres; s.state=S["S_BM_M3"]
        elif st==S["S_BM_M3"]:  s.mult_op_a=s.wa; s.mult_op_b=s.wc; s.mult_start=1; s.issues+=1; s.state=S["S_BM_M3W"]
        elif st==S["S_BM_M3W"]:
            if mdone: s.w_a0b0=mres; s.state=S["S_BM_WB0"]
        elif st==S["S_BM_WB0"]: s.mem_a_we=1; s.mem_a_wa=(s.bm_i<<1); s.mem_a_wd=add_y; s.state=S["S_BM_M4"]
        elif st==S["S_BM_M4"]:  s.mult_op_a=s.wa; s.mult_op_b=s.wd; s.mult_start=1; s.issues+=1; s.state=S["S_BM_M4W"]
        elif st==S["S_BM_M4W"]:
            if mdone: s.w_a0b1=mres; s.state=S["S_BM_M5"]
        elif st==S["S_BM_M5"]:  s.mult_op_a=s.wb; s.mult_op_b=s.wc; s.mult_start=1; s.issues+=1; s.state=S["S_BM_M5W"]
        elif st==S["S_BM_M5W"]:
            if mdone: s.w_a1b0=mres; s.state=S["S_BM_WB1"]
        elif st==S["S_BM_WB1"]: s.mem_a_we=1; s.mem_a_wa=(s.bm_i<<1)|1; s.mem_a_wd=add_y; s.state=S["S_BM_ADV"]
        elif st==S["S_BM_ADV"]:
            if s.cnt==127: s.state=S["S_INTT_INIT"]
            else:
                s.p_idx=(s.p_idx+s.stride)&0x7F; s.cnt+=1; s.bm_i=s.p_idx
                s.state=S["S_BM_LOAD"]
        elif st==S["S_INTT_INIT"]:
            s.layer=0; s.len_reg=2; s.k_base=126
            s._enter_layer(True)
            s.state=S["S_INTT_LOAD"]
        elif st==S["S_INTT_LOAD"]: s.wa,s.wb=a_rd0,a_rd1; s.state=S["S_INTT_SUM"]
        elif st==S["S_INTT_SUM"]: s.w_sum=add_y; s.w_diff=sub_y; s.state=S["S_INTT_MUL"]
        elif st==S["S_INTT_MUL"]: s.mult_op_a=Z_ntt; s.mult_op_b=s.w_diff; s.mult_start=1; s.issues+=1; s.state=S["S_INTT_MULW"]
        elif st==S["S_INTT_MULW"]:
            if mdone: s.w_t=mres; s.state=S["S_INTT_WB0"]
        elif st==S["S_INTT_WB0"]: s.mem_a_we=1; s.mem_a_wa=s.j_reg; s.mem_a_wd=s.w_sum; s.state=S["S_INTT_WB1"]
        elif st==S["S_INTT_WB1"]: s.mem_a_we=1; s.mem_a_wa=s.j_reg+s.len_reg; s.mem_a_wd=s.w_t; s.state=S["S_INTT_ADV"]
        elif st==S["S_INTT_ADV"]:
            if s.cnt != 127:
                s._adv_layer(True); s.state=S["S_INTT_LOAD"]
            else:
                if s.layer==6:
                    st2,sd2=s._draw(8); s.p_idx=st2; s.stride=sd2; s.cnt=0
                    s.scale_idx=st2; s.state=S["S_SCALE_INIT"]
                else:
                    s.k_base = s.k_base - (128>>s._lg(True))
                    s.layer+=1; s.len_reg<<=1
                    s._enter_layer(True); s.state=S["S_INTT_LOAD"]
        elif st==S["S_SCALE_INIT"]:
            st2,sd2=s._draw(8); s.p_idx=st2; s.stride=sd2; s.cnt=0; s.scale_idx=st2
            s.state=S["S_SCALE_LOAD"]
        elif st==S["S_SCALE_LOAD"]: s.wa=a_rd0; s.state=S["S_SCALE_MUL"]
        elif st==S["S_SCALE_MUL"]: s.mult_op_a=s.wa; s.mult_op_b=N_INV; s.mult_start=1; s.issues+=1; s.state=S["S_SCALE_MULW"]
        elif st==S["S_SCALE_MULW"]:
            if mdone: s.w_t=mres; s.state=S["S_SCALE_WB"]
        elif st==S["S_SCALE_WB"]: s.mem_a_we=1; s.mem_a_wa=s.scale_idx; s.mem_a_wd=s.w_t; s.state=S["S_SCALE_ADV"]
        elif st==S["S_SCALE_ADV"]:
            if s.cnt==255: s.state=S["S_DONE"]
            else:
                s.p_idx=(s.p_idx+s.stride)&0xFF; s.cnt+=1; s.scale_idx=s.p_idx
                s.state=S["S_SCALE_LOAD"]
        elif st==S["S_DONE"]: s.done=1
        s._lfsr_step()          # free-running, one shift per clock

def run(f,g,shared=True,shuffle=False,seed=0xACE12345,trace=False):
    c=Core(shared,shuffle,seed); c.mem_a=list(f); c.mem_b=list(g)
    prev=c.regs(); pwr=[]; cyc=0
    c.step(start_in=1)
    while c.state!=S["S_DONE"] and cyc < 80000:
        c.step(0); cyc+=1
        if trace:
            cur=c.regs(); pwr.append(sum(hw(a^b) for a,b in zip(prev,cur))); prev=cur
    return c, cyc, pwr
