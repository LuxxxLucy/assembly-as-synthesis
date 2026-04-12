# counterplan — assembly planning as program synthesis

> Assembly planning asks: *in what order can we build this?*
> We ask the next question: *when no order works, what is the smallest change that makes one possible?*

---

## The problem

Consider a stone arch. Once all the stones are in place, the arch is perfectly stable — compressive forces flow along the curved path and hold everything together. Try to build it one stone at a time, though, and each stone placed on the side topples: it needs the stone on the other side to push back. The arch is stable when *complete* but **impossible to build** sequentially.

This is not a planning failure; it is a geometric property of the structure. Every possible assembly order fails, because some intermediate step requires blocks that haven't been placed yet. Existing assembly planners (ASAP, Assemble Them All, Wang et al. 2025) assume such an order exists and search for it. When none exists they report failure and stop.

Counterplan addresses the complementary problem: **when no feasible sequence exists, what is the minimal modification that creates one?** Two strategies:

1. **Scaffolding** — add temporary supports (wooden centering, as real arches use).
2. **Geometry repair** — small adjustments to the block shapes so a feasible order becomes possible.

---

## The algorithm (faithful account)

### CEGIS with an extensible verifier chain

CEGIS stands for **Counterexample-Guided Inductive Synthesis** (Solar-Lezama 2008). Instead of enumerating all possible assembly orders, we learn from failed ones. Each CEGIS round:

```
1. PROPOSE a candidate order
   Kahn's topological sort with random tie-breaking, constrained by the precedence
   constraints learned so far. If the constraint graph has a cycle, we return
   INFEASIBLE — no order can satisfy all constraints.

2. VERIFY each placement step with a chain of verifiers.
   The chain is the extension point: each verifier contributes its own class of
   precedence constraints. Default chain (cheapest-first):

     (i)   KinematicVerifier   — fall-path clearance
             Build the block's swept volume along the descent direction
             (gravity, or arbitrary per-block direction). If any already-placed
             block intersects that sweep, the block cannot be brought into
             position — learn B ≺ blocker.

     (ii)  StabilityVerifier   — static equilibrium
             Solve an LP: do feasible contact forces exist under gravity
             satisfying force balance, moment balance, compression-only,
             and friction cone? On infeasibility, call find_minimal_support_set
             to identify absent below-neighbors whose presence would restore
             stability — learn {supports} ≺ B.

     (iii) LandingVerifier     — block actually settles at target
             Translate the block a small ε along the descent direction and
             check it intersects the ground or a placed block. If not, the
             target is unsupported and the block would fall past it — learn
             below-neighbors ≺ B.

3. On the first verifier failure at step k: record precedence constraints,
   break out of the step loop, propose a new order next round.

4. TERMINATE on success (feasible sequence) or cycle (INFEASIBLE).
```

Each verifier returns `VerifierResult(feasible, new_constraints, diagnostics)`. Adding a new verifier (robot reach, footprint, no-flip, reorientation cost) is a drop-in extension — no changes to the CEGIS loop or trace format.

In practice on the current demo set, stability and kinematic do all the constraint-learning work — landing is dominated (whenever it would fire, stability has already rejected the step). Landing is kept in the chain as a cheap independent sanity check and as a template for how a third kind of verifier integrates.

### Why the chain needed three verifiers

Stability-only CEGIS was incorrect: it accepted sequences that are stable in their final state but physically unconstructible because later blocks block the drop path of earlier ones. For example, placing a row-2 block before the row-1 block beneath it: stability says "row-2 block rests fine on row-0 blocks at the sides"; reality says "the row-1 block can no longer descend into its slot because row-2 is on top." The kinematic verifier catches exactly this.

Landing is the symmetric sanity check: the block must not just *be placed in equilibrium* (stability), it must *physically arrive* at the target position by falling (landing). The three verifiers together approximate the three requirements of a real pick-and-place: reachable path, stable equilibrium at target, and target is actually a landing spot.

### Counterexample generalization (stability case)

When stability fails for block B with blocks `placed` already down, we don't just reject this one ordering — we extract a **minimal support set**: the smallest subset of absent blocks that must precede B for stability. Procedure in `find_minimal_support_set`:

1. Enumerate B's neighbors from the full-structure contact graph.
2. Filter to *below-neighbors* (top edge at or under B's bottom edge). Above-neighbors cannot structurally support; they can only obstruct — which the kinematic verifier handles. If no below-neighbors exist (lateral-thrust cases: arch voussoirs push sideways, not downward), fall back to all absent neighbors.
3. Greedy minimization: for each candidate, test whether `structure minus candidate` still leaves B stable. If yes, `candidate` is redundant.
4. Return the remaining necessary neighbors as precedence constraints `necessary ≺ B`.

This is the analogue of **CDCL clause learning**: one conflict prunes an exponential region of the permutation space, not just one order. A 10-block pyramid has 3,628,800 orderings; CEGIS converges in ~7 rounds, learning ~10 precedence constraints total.

The analogy is not exact: CDCL clauses are derived by resolution and are logically minimal; our precedence constraints are *sound but potentially conservative* (the true requirement may be "A or C must support B," we learn the stronger "A ≺ B"). This is documented in `verify.md` (Claim 5).

---

## Code structure

```
assembly-as-synthesis/
├── src/counterplan/
│   ├── geometry.py           # Block, Contact, Structure; polygonal contact detection
│   ├── stability.py          # LP solver + find_minimal_support_set (Scipy linprog/HiGHS)
│   ├── cegis.py              # Main loop; verifier-chain-agnostic
│   ├── verifiers/            # The extension point
│   │   ├── base.py           # Verifier protocol, VerifierResult, PrecedenceConstraint
│   │   ├── kinematic.py      # Fall-path sweep intersection (shapely)
│   │   ├── stability.py      # LP wrapper
│   │   └── landing.py        # ε-downward probe for target-landing
│   ├── structures.py         # Pre-built demos (arch, pyramid, wall, …)
│   ├── repair.py             # Heuristic vertex perturbation for infeasible structures
│   ├── scaffolding.py        # CEGIS-squared: synthesise temporary supports
│   ├── viz.py                # Matplotlib 2D renders (legacy, still used by examples/demo.py)
│   └── trace.py              # JSON export — the ONLY bridge from algorithm to web viz
├── examples/
│   ├── demo.py               # Matplotlib gallery + repair demos
│   └── export_traces.py      # Rebuilds web/data/*.json from current structures
├── tests/
│   └── test_kinematic.py     # Unit + integration tests for the verifier chain
└── web/
    ├── index.html            # Single-file, importmap-based Three.js demo
    ├── app.js                # 3D viewer (consumes trace JSON; zero algorithm logic)
    ├── style.css             # Polar Void palette
    └── data/*.json           # Pre-computed traces (schema: counterplan-trace/2)
```

**Separation of algorithm and visualization.** The Python package produces a `CEGISResult`. `trace.py` serialises it to JSON with a schema tag. The web viewer parses that JSON and has no other contract with the solver — replace the solver, keep the viewer, or vice versa. The JSON includes per-step verifier results so the viewer can colour constraint arrows by source (kinematic = sand, stability = terracotta, landing = gray).

**3D viewer.** `web/app.js` uses `THREE.ExtrudeGeometry` to turn each 2D polygon into an extruded prism along z. Blocks drop in from +y with ease-out cubic, failed blocks tumble off (visible gravity), precedence constraints render as coloured bezier-tube arcs between block centroids. The aesthetic is a stacking-game: each block falls into its target; unstable proposals literally fall away. Styling follows the Polar Void palette (cold, near-neutral, architectural).

---

## Test structures

| Structure | Blocks | Feasible? | Why |
|-----------|:------:|:---------:|-----|
| Wall 4    | 4  | ✓ | Trivial bottom-up |
| Pyramid 6 | 6  | ✓ | Bottom-up, 2 CEGIS rounds |
| **Pyramid 10** | 10 | ✓ | 3.6M orderings, solves in ~7 rounds; requires **kinematic** constraints to reject mid-row inversions |
| Post & Lintel | 5 | ✓ | Learns "columns ≺ lintel" in 3 rounds |
| Arch 5    | 5  | ✗ | Cyclic stability — voussoirs need mutual thrust |
| Arch 7    | 7  | ✗ | Same cycle, larger |
| Gothic Arch 9 | 9 | ✗ | Pointed geometry, high horizontal thrust |
| Unstable Tower | 3 | (LP-feasible) | Narrow-base inverted pyramid — flagged for repair |
| Cantilever 5 | 5 | ✗ | Progressive overhangs — flagged for repair |

---

## Running

```bash
cd projects/2026-03-assembly-as-synthesis/assembly-as-synthesis

# Run tests
uv run --with pytest pytest tests/ -v

# Regenerate traces for the web viewer (runs CEGIS on every demo with seed=42)
uv run python examples/export_traces.py

# Launch the viewer
cd web && python -m http.server 8080
# → open http://localhost:8080
```

`export_traces.py` hardcodes `seed=42` so traces are reproducible. Pass a different seed (or remove it) to explore alternative feasible orderings.

Arrow keys step through frames; space toggles playback; drag to orbit.

---

## Current limitations

- **2D only.** The algorithm is planar; the web viewer extrudes for visual 3D. A true 3D contact/stability generalisation is future work.
- **Scaffolding and repair do not yet consume kinematic/landing constraints** — they were written against the stability-only interface. Extending them to the full chain is straightforward (the constraint set already carries `source` tags) but not done.
- **Greedy support-set minimisation** is sound but not guaranteed minimal (see verify.md Claim 5). A Farkas-certificate-guided version could produce tighter constraints.
- **Gothic arch scaffolding fails** — curved centring needed, not simple columns.
- **Scale unvalidated above ~10 blocks.** Contact graphs are sparse, so CEGIS should stay efficient to ~20 blocks, but this is not yet tested.

---

*counterplan v0.3 — April 2026. ~1,400 LOC Python, ~400 LOC JS. Dependencies: numpy, scipy, shapely, matplotlib; Three.js via CDN.*
