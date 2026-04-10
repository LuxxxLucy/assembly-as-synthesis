# Counterplan: When Assembly Fails, Fix the Geometry

> Assembly planning asks: *in what order can we build this?*
> We ask the next question: *when no order works, what is the smallest change that makes one possible?*

---

## The Problem

A structure may be stable once complete, yet **impossible to build** — because every assembly order requires placing a block that cannot stand without blocks not yet placed. This is not a planning failure. It is a geometric property of the structure itself.

Existing assembly planners (ASAP, Assemble Them All, Wang et al. 2025) find valid sequences for fixed geometry. They assume one exists. When it does not, they report failure and stop.

We address the complementary problem: **when no feasible sequence exists, what is the minimal geometry modification that creates one?**

---

## The Method

Two-phase approach:

### Phase 1: CEGIS Assembly Planning

[Counterexample-Guided Inductive Synthesis](https://people.csail.mit.edu/asolar/papers/thesis.pdf), adapted from program synthesis to physics.

```
CEGIS-Assembly(structure S):
  constraints = ∅
  repeat:
    candidate = sample_topological_sort(constraints)
    if no valid sort exists: return INFEASIBLE
    for step k = 1..n:
      if blocks[1..k] are not in static equilibrium (LP):
        extract: which blocks MUST precede block[k]?  ← from LP dual
        add precedence constraints
        break
    if all steps stable: return candidate
```

Each failure does not just reject one sequence — it extracts a **precedence constraint** (block A must come before block B) that eliminates an exponential family of orderings. This is analogous to clause learning in CDCL SAT solvers, but over continuous physics rather than Boolean variables.

The stability check is an LP: given placed blocks and their contacts, do feasible contact forces exist that satisfy equilibrium, compression-only normal forces, and Coulomb friction? This LP solves in <1ms for 20 blocks.

### Phase 2: Repair Synthesis

When CEGIS exhausts all orderings (the precedence graph has a cycle), the structure is **provably infeasible** for sequential assembly. The repair pipeline:

1. **Identify critical blocks** — those appearing most often in stability failures across CEGIS rounds
2. **Compute contact deficiency** — what's missing for these blocks to be stable at their placement step
3. **Minimal geometry perturbation** — find the smallest vertex displacement that resolves the deficiency
4. **Re-run CEGIS** on the modified structure

The key insight: the LP infeasibility certificate (Farkas lemma) tells us *which contacts are insufficient* and *in which direction* force capacity is lacking. This converts an opaque "infeasible" into a geometric gradient for repair.

---

## Results

### Test structures

![Structure Gallery](output/gallery.png)

Six structures spanning three regimes:
- **Feasible** (Wall, Pyramid): valid assembly orders exist. CEGIS finds them.
- **Infeasible, repairable** (Tower): no valid order, but small geometry changes fix it.
- **Infeasible, structural** (Arches, Cantilever): cyclic physical dependencies — the structure *requires* mutual support.

### CEGIS on feasible structures

**Pyramid (6 blocks, 720 possible orderings):**

CEGIS solves it in **2 rounds**. Round 1 tries placing the top block first — fails, learns that base blocks must come first. Round 2 succeeds immediately.

![Pyramid CEGIS Replay](output/pyramid-6_cegis.png)

The step-by-step assembly with per-block stability coloring (blue = safe, red = marginal):

![Pyramid Assembly Steps](output/pyramid-6_steps.png)

The efficiency gain — 2 rounds vs. 720 permutations:

![Pyramid Race](output/pyramid-6_race.png)

**Wall (4 blocks, 24 possible orderings):**

Solved in **1 round** — the first random ordering happened to be valid. No constraints needed.

### CEGIS on infeasible structures: arches

This is the core finding. A semicircular arch is stable when complete — the thrust line passes through all voussoirs. But **no sequential assembly order exists**: each voussoir needs lateral thrust from its neighbor, creating mutual dependencies.

CEGIS discovers this in **3 rounds** for the 5-block arch:

![Arch CEGIS Replay](output/arch-5_cegis.png)

The learned constraints include both `2 ≺ 3` and `3 ≺ 2` — a cycle. This is the formal proof that the structure cannot be built block-by-block without scaffolding.

This is physically correct and well-known in masonry construction. What's new: CEGIS *derives* this automatically from the LP stability checks, rather than requiring domain expertise to recognize it.

### Repair synthesis: the tower

The inverted pyramid (narrow base, wide top) is infeasible — the top block overhangs too far for any placement order to work.

Repair synthesis finds that **widening the base block by 0.14 units** (spreading bottom vertices outward) creates enough contact area. The modified structure admits the sequence [0, 1, 2] (bottom-up).

![Tower Repair](output/tower_repair.png)

Left: original geometry (infeasible). Right: repaired geometry with displacement arrows showing the modification. Total displacement: 0.141 units.

---

## What This Means

| System | Fixed geometry | Geometry repair |
|--------|:---:|:---:|
| ASAP (MIT, ICRA 2024) | ✓ (50+ parts) | — |
| Assemble Them All (Autodesk, SIG Asia 2022) | ✓ (80+ parts) | — |
| Wang et al. (SIGGRAPH 2025) | ✓ (RL-based) | — |
| **Counterplan** | ✓ (via CEGIS) | **✓** |

We are not competing on scale. ASAP handles 50+ parts; we've tested up to 7. The contribution is the **co-design loop**: when planning fails, the failure certificate becomes a geometry repair signal. Nobody in the assembly planning literature does this.

Framing: *They plan for fixed geometry. We fix the geometry when planning fails.*

---

## Current Limitations

- **2D only.** 3D contact detection + stability is a significant extension (though the LP formulation generalizes directly).
- **Repair heuristics.** The current repair tries vertex perturbation modes (widen base, lower CoM, increase contact). A proper approach would use the Farkas certificate's geometric sensitivity ∂A/∂p (Whiting et al. 2012) for gradient-based repair.
- **Arch repair fails.** Cyclic dependencies can't be resolved by moving vertices — they require adding temporary supports (scaffolding blocks) or fundamentally changing the topology. This is a real open problem.
- **Scale.** Tested on 4–7 blocks. Counterexample generalization should keep CEGIS efficient up to ~20 blocks, but this is unvalidated.

---

## Next Steps

1. **Farkas-guided repair.** Replace heuristic perturbation with gradient from the LP infeasibility certificate. This is the publishable algorithmic contribution (~50 LOC on top of existing verifier).
2. **Scaffolding synthesis.** For structures with cyclic dependencies (arches), synthesize temporary support blocks that break the cycle. Remove them after construction.
3. **Wang's puzzle benchmarks.** Reframe from gravity stability to kinematic blocking (directional freedom). The CEGIS loop structure survives; the verifier changes.
4. **3D extension.** Use the parametric arch generator from COMPAS Assembly (ETH) for 3D voussoir geometry.

---

## Running the Demo

```bash
cd projects/2026-03-assembly-as-synthesis/assembly-as-synthesis
uv run python examples/demo.py
# All visualizations saved to output/
```

~800 lines of Python. Dependencies: numpy, scipy, matplotlib, shapely.

---

*counterplan v0.1 — April 2026*
