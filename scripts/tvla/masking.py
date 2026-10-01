"""Additive (arithmetic) masking of the secret operand using the UNMODIFIED core.

h = f*g ; split f = f1 + f2 (mod q) with f1 uniform random. By linearity of the
NTT/INTT and bilinearity of the base multiplication
    INTT(NTT(f1).NTT(g)) + INTT(NTT(f2).NTT(g)) = INTT(NTT(f1+f2).NTT(g)) = h
so two invocations of the existing core, plus a 256-coefficient modular addition
of the two results performed OUTSIDE the core, reproduce the product exactly.
No RTL change is involved.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core_model as cm  # noqa: E402

Q = 3329


def masked_run(f, g, rng, trace=False):
    """Run the core twice on (f1,g) and (f2,g); return (recombined, cycles, trace)."""
    f1 = [rng.randrange(Q) for _ in range(256)]
    f2 = [(a - b) % Q for a, b in zip(f, f1)]
    c1, cy1, p1 = cm.run(f1, g, True, trace=trace)
    c2, cy2, p2 = cm.run(f2, g, True, trace=trace)
    out = [(a + b) % Q for a, b in zip(c1.mem_a, c2.mem_a)]
    return out, cy1 + cy2, (p1 + p2 if trace else [])
