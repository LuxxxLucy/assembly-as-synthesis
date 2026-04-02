# Assembly as Synthesis: Deep Research Report
## E-Graphs, CEGIS, and the Path Forward

> Research on whether egg/e-graphs, brute-force CEGIS, or hybrid approaches
> are the right substrate for assembly sequence synthesis.

---

## TL;DR — The Opportunity

**Nobody has combined e-graphs with physical feasibility constraints for assembly planning.**

The closest work is **Szalinski** (PLDI 2020), which uses equality saturation to restructure
flat CSG (Constructive Solid Geometry) programs into hierarchical ones. A flat assembly
sequence is *exactly* a flat CSG program. But Szalinski's rewrites only preserve geometric
identity — they don't check physical stability. Adding stability as an **e-class analysis**
in egg would be the novel contribution.

A very recent paper — **CE-graphs** (SMT 2025, Frankel et al.) — directly combines CEGIS
with e-graphs: each counterexample builds an e-graph of all programs satisfying the spec
on that counterexample; successive e-graphs are intersected. This is the exact mechanism
for assembly: each collapsed arch produces a CE-graph of plans that avoid that failure,
and intersection converges to valid plans.

---

## Key Papers (Organized by Relevance)

### Tier 1: Directly Analogous

| Paper | Venue | Key Idea | Assembly Connection |
|---|---|---|---|
| **Szalinski** (Nandi, Willsey et al.) | PLDI 2020 | E-graph + inverse transforms restructure flat CSG into hierarchical programs | Flat assembly sequence = flat CSG. Sub-assembly discovery = loop rerolling |
| **CE-graphs** (Frankel et al.) | SMT 2025 | CEGIS loop where each CX builds an e-graph of valid programs; intersect successively | Failed assemblies → CE-graphs → intersection → valid plan space |
| **Guided Equality Saturation** (Koehler et al.) | POPL 2024 | User-provided "shape sketches" factor saturation into manageable stages | Assembly milestones as sketch guides → avoid e-graph explosion |
| **Refactoring with Synthesis** (Raychev et al.) | OOPSLA 2013 | CEGIS infers refactoring sequences from partial user edits | User partially specifies assembly intent → CEGIS completes it |

### Tier 2: Infrastructure & Theory

| Paper | Venue | Key Idea | Assembly Connection |
|---|---|---|---|
| **egg** (Willsey et al.) | POPL 2021 | Fast equality saturation with e-class analyses and rebuilding | Core substrate; e-class analysis = stability predicate attachment |
| **egglog** (Willsey et al.) | PLDI 2023 | Unifies Datalog + equality saturation for relational reasoning | Precedence constraints as Datalog relations maintained during saturation |
| **Ruler** (Nandi, Willsey et al.) | OOPSLA 2021 | Automatically infer rewrite rules from black-box interpreter | Bootstrap assembly transformation rules from physics simulator |
| **Enumo** (Nandi et al.) | OOPSLA 2023 | DSL for domain-specific theory exploration | Semi-automated discovery of assembly equivalence rules |
| **Rosetta Stone** (Wang et al.) | EGRAPHS 2022 | E-graphs ≅ VSAs ≅ finite-state tree automata | Bridges inductive synthesis (examples) and equality saturation (rewrites) |

### Tier 3: Extraction Under Constraints

| Paper | Venue | Key Idea | Assembly Connection |
|---|---|---|---|
| **Sparse Extraction** (Goharshady et al.) | OOPSLA 2024 | Optimal extraction via treewidth DP; tractable when e-graph is sparse | Assembly graphs are typically sparse → tractable extraction |
| **SmoothE** (Cai et al.) | ASPLOS 2025 (Best Paper) | Differentiable e-graph extraction via gradient descent | Non-linear feasibility costs (stability margins) become differentiable objectives |
| **E-Graphs as Circuits** (Sun et al.) | arXiv 2024 | E-graphs = monotone Boolean circuits; treewidth transfer | Pre-processing reduces graph size 40-80% |

### Tier 4: Original CEGIS (No Neural Networks)

| Paper | Venue | Key Idea |
|---|---|---|
| **SKETCH** (Solar-Lezama et al.) | ASPLOS 2006 | SAT-based CEGIS: holes encoded as boolean formula, no enumeration |
| **CEGIS(T)** (Abate, Kroening et al.) | CAV 2018 | Extends CEGIS to SMT: integers, arrays, linear arithmetic |
| **SyGuS** (Alur, Bodik et al.) | FMCAD 2013 | Syntax-guided synthesis; enumerative CEGIS sometimes beats pure SAT |
| **Equiv. by Canonicalization** (Lubin et al.) | PLDI 2024 | Canonical forms replace SMT in synthesis-backed refactoring |

---

## Three Candidate Architectures

### Option A: Pure E-Graph Approach (No Learning)

```
Structure geometry
       │
       ▼
  Flat assembly sequence (one valid ordering, found by any method)
       │
       ▼
  Insert into e-graph (egg/egglog)
       │
       ▼
  Apply rewrite rules:
    - Commutativity: swap independent steps
    - Inverse transforms: factor out sub-assembly patterns (Szalinski-style)
    - Hold optimization: minimize simultaneous holds
       │
       ▼
  Extraction with stability constraint:
    - E-class analysis: each e-class carries stability feasibility flag
    - Extract minimum-cost plan where all intermediate states are stable
       │
       ▼
  Valid, optimized assembly plan
```

**Pros:** Fully symbolic, verifiable, no training. Reuses mature egg infrastructure.
**Cons:** Need an initial valid plan to seed the e-graph. Rewrite rules must be manually
authored or discovered via Ruler. Stability check during extraction is non-local
(violates additive cost assumption — needs SmoothE or ILP side constraints).

### Option B: CEGIS + E-Graph Hybrid (CE-Graph Approach)

```
Structure geometry
       │
       ▼
  ┌─────────────────────────────────────────────┐
  │             CEGIS LOOP                      │
  │                                             │
  │  Synthesizer: enumerate candidate plans     │
  │  (brute-force or SAT-encoded)               │
  │       │                                     │
  │       ▼                                     │
  │  Verifier: physics simulator                │
  │       │                                     │
  │    stable? ─── YES ──► return plan          │
  │       │                                     │
  │       NO                                    │
  │       │                                     │
  │       ▼                                     │
  │  Build CE-graph: e-graph of all plans       │
  │  that avoid THIS failure mode               │
  │       │                                     │
  │  Intersect with previous CE-graphs          │
  │       │                                     │
  │  Extract next candidate from intersection   │
  │       │                                     │
  │       └──────────── loop ──────────────────┘│
  └─────────────────────────────────────────────┘
```

**Pros:** Each counterexample eliminates *entire equivalence classes* of bad plans,
not just one plan. Converges exponentially faster than naive enumeration.
No neural networks needed. Formal convergence guarantee if plan space is finite.
**Cons:** CE-graph intersection is new (only one paper, SMT 2025). Physics simulator
as verifier is expensive. May need guided saturation to control e-graph size.

### Option C: Guided Equality Saturation with Sketch Milestones

```
  Human / high-level planner provides sketch:
    "left pier → right pier → springer pair → voussoirs → keystone"
       │
       ▼
  For each sketch stage:
    Insert candidate sub-plans into e-graph
    Apply rewrite rules (commutativity, hold optimization)
    Saturate within stage (bounded, won't explode)
    Extract best sub-plan with stability constraint
       │
       ▼
  Compose stage plans into full assembly plan
  Verify end-to-end stability
       │
       ▼
  If any stage fails: CEGIS feedback to refine sketch
```

**Pros:** Controlled e-graph size (guided, won't explode). Natural human-in-the-loop:
architect provides coarse intent. Combines the best of sketch completion and
equality saturation. POPL 2024 paper shows this handles cases where unguided
saturation fails (7/7 matrix multiply optimizations recovered).
**Cons:** Requires meaningful sketch decomposition. Quality depends on sketch granularity.

---

## Why E-Graphs are a Good Direction (Not Just Neural Policies)

### 1. The Phase-Ordering Problem
Wang et al.'s beam search commits to decisions greedily. E-graphs avoid this:
they represent ALL equivalent orderings simultaneously and extract the best one
at the end. TENSAT showed this beats backtracking search on tensor graphs.

### 2. Compositionality via Inverse Transforms
Szalinski showed that inverse transformations let e-graphs discover hierarchical
structure (sub-assemblies) in flat sequences. This is exactly the "library learning"
idea from our brainstorm, but achieved via rewriting rather than statistical compression.

### 3. The Precedence Problem Has a Solution: egglog
Standard e-graphs represent pure functional terms. Assembly sequences have ordering
constraints ("part A before part B"). egglog extends egg with Datalog relations,
which can maintain precedence as a relation updated during saturation.

### 4. Extraction Under Physical Constraints
SmoothE (ASPLOS 2025 Best Paper) enables differentiable extraction with non-linear
cost functions. Stability margin is differentiable. This is the extraction mechanism
that makes the whole thing work.

### 5. Rule Discovery is Automatable
Ruler and Enumo can automatically discover valid assembly rewrite rules from a
physics simulator, rather than requiring manual encoding.

---

## Why Brute Force + CEGIS (No E-Graphs) Is Also Viable

For **small assemblies** (< 20 parts), the original Solar-Lezama approach may suffice:

1. Encode the plan space as a SAT/SMT formula (part ordering variables + stability constraints)
2. Use CEGIS: solver proposes plan → simulator checks → counterexample refines formula
3. No e-graph needed — the SMT solver handles equivalence internally

**The SyGuS lesson:** Pure enumeration sometimes beats SAT on small, well-structured problems.
For assemblies with < 15 parts, brute-force enumeration with stability pruning may be the
simplest and most effective approach. CEGIS becomes necessary for larger assemblies where
the brute-force explosion is intractable.

---

## The Novel Research Contribution (The Gap)

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   egglog (relational saturation for precedence constraints) │
│         +                                                   │
│   Szalinski-style inverse transforms (AC-matching)          │
│         +                                                   │
│   CE-graph CEGIS (stability failures as counterexamples)    │
│         +                                                   │
│   SmoothE extraction (differentiable stability cost)        │
│                                                             │
│   = Assembly Equality Saturation (AES)                      │
│                                                             │
│   NOBODY HAS DONE THIS COMBINATION.                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

The claim: **Assembly Equality Saturation** (AES) compactly represents the space of
all equivalent assembly plans in an e-graph, uses physics-grounded rewrite rules
(discovered via Ruler) to expand equivalences, maintains precedence via egglog's
Datalog layer, and extracts optimal plans via SmoothE's differentiable extraction
with stability margin as the cost function. CEGIS drives the loop: each failed
simulation produces a CE-graph that prunes the plan space.

This is a PLDI/POPL-level contribution with SIGGRAPH-level demos.

---

## "Refactoring by Synthesis" Connection

The paper is **"Refactoring with Synthesis"** by Raychev, Schäfer, Sridharan, Vechev (OOPSLA 2013).

**Core idea:** User partially performs a refactoring → CEGIS infers the complete refactoring
sequence that reproduces the user's changes.

**Assembly analog:** Architect partially specifies an assembly intent (e.g., "I want to build
the left pier first") → CEGIS infers the complete hold/remove sequence that realizes the
intent while maintaining stability. This is exactly Option C (Guided EqSat with Sketch Milestones)
where the "sketch" is the architect's partial intent.

The key insight from this paper: **synthesis doesn't need a complete spec — a partial
demonstration is enough.** For assembly: the architect doesn't write a full stability spec;
they show a few steps and the system completes the plan.

---

## Recommended Reading Order

1. **egg** (POPL 2021) — understand the substrate
2. **Szalinski** (PLDI 2020) — see the CSG/assembly analogy
3. **Guided Equality Saturation** (POPL 2024) — understand how to control explosion
4. **CE-graphs** (SMT 2025) — see CEGIS + e-graph combination
5. **SmoothE** (ASPLOS 2025) — understand constrained extraction
6. **egglog** (PLDI 2023) — understand relational extension for precedence
7. **Ruler** (OOPSLA 2021) — understand automated rule discovery
8. **Refactoring with Synthesis** (OOPSLA 2013) — see partial-spec CEGIS
