# Counterplan: When Assembly Fails, Fix the Geometry

> Assembly planning asks: *in what order can we build this?*
> We ask the next question: *when no order works, what is the smallest change that makes one possible?*

---

## The Problem

Consider a stone arch. Once all the stones are in place, the arch is perfectly stable — compressive forces flow along the curved path and hold everything together. But try to build it one stone at a time: each stone you place on the side will topple over, because it needs the stone on the other side to push against. The arch is stable when *complete*, yet **impossible to build** sequentially.

This is not a planning failure. It is a geometric property of the structure itself. Every possible assembly order fails, because some intermediate step requires blocks that haven't been placed yet.

Existing assembly planners (ASAP, Assemble Them All, Wang et al. 2025) assume a feasible assembly order exists. They search for it. When none exists, they report failure and stop.

We address the complementary problem: **when no feasible sequence exists, what is the minimal modification that creates one?** Two strategies:

1. **Scaffolding** — add temporary supports (like the wooden centering used in real arch construction)
2. **Geometry repair** — make small adjustments to the block shapes so a feasible order becomes possible

---

## How CEGIS Works

CEGIS stands for **Counterexample-Guided Inductive Synthesis**, a technique from program synthesis (Solar-Lezama, 2008). The core idea: instead of searching through all possible solutions, we *learn from failures*.

### The Loop

```
1. PROPOSE a candidate assembly order
   (random permutation, but consistent with what we've learned so far)

2. VERIFY each step by physics simulation:
   "If I place these blocks in this order, does each intermediate
    configuration stay standing?"

   → We check this with a Linear Program (LP). Given the blocks placed
     so far and their contact geometry, do feasible contact forces exist
     that satisfy:
       - Force balance (the block doesn't accelerate)
       - Moment balance (the block doesn't rotate)
       - Compression only (blocks push, never pull)
       - Friction limits (blocks don't slide)

3. On FAILURE at step k (block B is unstable):
   GENERALIZE — don't just reject this one ordering.
   Ask: "What blocks are MISSING that block B needs for support?"

   → We identify the minimal set of absent blocks whose presence
     would make B stable. These become PRECEDENCE CONSTRAINTS:
     "block X must be placed before block B."

4. REPEAT with the new constraints. Each constraint eliminates
   an exponential family of orderings (not just one).

5. TERMINATE when either:
   - A feasible sequence is found (SUCCESS), or
   - The constraints form a CYCLE (A must come before B, and B must
     come before A) — proving no sequential order exists (INFEASIBLE).
```

### Why This is Efficient

A 10-block pyramid has 10! = 3,628,800 possible assembly orderings. Brute force checks each one. CEGIS solves it in **2 rounds**:
- Round 1: tries placing top blocks first → fails → learns "bottom row must come first"
- Round 2: respects the constraint → succeeds immediately

The key insight is **counterexample generalization**: one failure doesn't just eliminate one bad ordering — it eliminates all orderings that make the same structural mistake. This is analogous to **clause learning in SAT solvers** (CDCL), where a single conflict prunes exponential regions of the search space.

### Constraint Learning via LP Dual

When block B fails at step k, the LP (stability check) is infeasible. To identify which missing blocks would help, we:

1. Find all neighbors of B in the full structure (from the contact graph)
2. Identify which neighbors are absent (not yet placed)
3. Check: adding ALL absent neighbors — does B become stable?
4. If yes, greedily minimize: remove each neighbor one at a time, keeping only those whose removal breaks stability

This produces the **minimal support set** — the tightest possible precedence constraints, pruning the maximum number of orderings per round.

---

## Test Structures

We provide a gallery of structures spanning three regimes:

### Feasible Structures (valid assembly orders exist)

| Structure | Blocks | Orderings | CEGIS Rounds |
|-----------|:------:|:---------:|:------------:|
| Wall | 4 | 24 | 1 |
| Pyramid (6) | 6 | 720 | 2 |
| **Pyramid (10)** | 10 | 3,628,800 | **2** |
| **Post & Lintel** | 5 | 120 | 3 |

The **Post & Lintel** (Stonehenge-like: two columns + spanning beam) demonstrates clean constraint learning: CEGIS quickly learns "columns before lintel."

The **Pyramid (10)** shows CEGIS efficiency at scale: 3.6M orderings, solved in 2 rounds.

### Infeasible Structures (cyclic dependencies, need scaffolding)

| Structure | Blocks | Detected In | Cycle |
|-----------|:------:|:-----------:|-------|
| Semicircular Arch | 5 | 3 rounds | voussoirs need mutual support |
| **Gothic Pointed Arch** | 9 | 2 rounds | high thrust, steep geometry |

The **Gothic Pointed Arch** has two circular arcs meeting at a peak. The pointed geometry creates high horizontal thrust — voussoirs can't stand without lateral compression from their neighbors, creating mutual dependencies that CEGIS detects as cycles.

---

## Scaffolding Synthesis (CEGIS-squared)

When CEGIS proves a structure is infeasible (cyclic constraints), we don't stop. We add **temporary support blocks** — scaffolding — that break the cycle.

The algorithm is itself a CEGIS loop (hence "CEGIS-squared"):

```
OUTER LOOP: synthesize scaffold configurations
  1. Find blocks involved in cyclic constraints
  2. Generate candidate scaffolds (vertical columns from ground
     to the underside of each cycle block)
  3. INNER LOOP: run CEGIS on the augmented structure
     (original blocks + scaffolds)
  4. VERIFY: after all blocks are placed, is the structure
     self-supporting WITHOUT the scaffolds?
     (One LP check on the complete structure minus scaffolds)
  5. If yes → return the sequence + scaffold removal plan
     If no → try more/different scaffolds
```

This mirrors real masonry construction: arches are built on wooden **centering** (temporary curved formwork). Once the keystone is placed and the arch is complete, the centering is removed — the arch supports itself through compression.

**Result on Semicircular Arch (5 blocks):**
- Original CEGIS: 3 rounds → INFEASIBLE (cyclic constraints 2≺3 and 3≺2)
- With 2 scaffold columns: CEGIS finds sequence in 2 rounds
- Removal verification: complete arch is self-supporting ✓

---

## Visualization

### Animated CEGIS Replay

The negotiation replay shows the CEGIS loop as an animation:
- **Propose**: ghost blocks appear in target positions
- **Place**: blocks descend into position one by one (terracotta → blue)
- **Fail**: unstable block flashes red
- **Learn**: constraint arrows appear between blocks
- **Rewind**: blocks fade out in reverse order
- **Retry**: new round begins with updated constraints

Available as:
- **MP4/GIF** via matplotlib animation (`animate_negotiation_replay()`)
- **Interactive web viewer** (`web/index.html` — open in browser, arrow keys to step through)

### Color Palette: Polar Void

Cold, austere, near-neutral — inspired by the Obsidian Velocity theme:
- Background: `#1A1D23` (near-black, cold blue undertone)
- Blocks: `#7BA4C7` (steel blue)
- Active block: `#D97757` (Anthropic terracotta)
- Failure: `#BF616A` (muted red)
- Success: `#8FBCA3` (sage green)
- Typography: Inter (body) + JetBrains Mono (code/labels)

---

## Comparison

| System | Fixed geometry | Scaffolding | Geometry repair |
|--------|:---:|:---:|:---:|
| ASAP (MIT, ICRA 2024) | ✓ (50+ parts) | — | — |
| Assemble Them All (Autodesk, SIG Asia 2022) | ✓ (80+ parts) | — | — |
| Wang et al. (SIGGRAPH 2025) | ✓ (RL-based) | — | — |
| **Counterplan** | ✓ (via CEGIS) | **✓** | **✓** |

We are not competing on scale. The contribution is the **co-design loop**: when planning fails, the failure certificate becomes actionable — either scaffolding synthesis or geometry repair.

---

## Current Limitations

- **2D only.** 3D contact detection + stability generalizes (same LP formulation), but not yet implemented.
- **Scaffolding placement is heuristic** — vertical columns under cycle blocks. A gradient-based approach using the LP dual could find optimal placement.
- **Constraint learning is greedy** — finds a minimal support set but not necessarily the strongest possible constraint. The LP Farkas certificate could guide tighter cuts (analogous to 1-UIP in CDCL SAT solvers).
- **Scale.** Tested on 4–10 blocks. The counterexample generalization should keep CEGIS efficient up to ~20 blocks (contact graphs are sparse), but this is unvalidated.
- **Gothic arch scaffolding fails** — the pointed geometry creates non-trivial force paths that simple column scaffolds don't resolve. Curved centering (matching the intrados) would work but requires multi-block scaffold representation.

---

## Running

```bash
# Python demos (matplotlib output)
cd projects/2026-03-assembly-as-synthesis/assembly-as-synthesis
uv run python examples/demo.py

# Web viewer (open in browser)
cd web && python -m http.server 8080
# → http://localhost:8080
```

~1200 lines of Python. Dependencies: numpy, scipy, matplotlib, shapely.

---

*counterplan v0.2 — April 2026*
