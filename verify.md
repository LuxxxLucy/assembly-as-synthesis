# Novelty Verification: Counterplan Claims

> 15 independent research agents checked our core claims from multiple angles. This document reports findings honestly, including near-misses and caveats.

---

## Claim 1: Existing assembly planners only handle fixed geometry

**Verdict: CONFIRMED.**

| System | What it does | Geometry repair? |
|--------|-------------|:---:|
| ASAP (Tian et al., ICRA 2024) | Tree search + GNN for sequence planning, 50+ parts | No. Reports failure and stops. |
| Assemble Them All (Tian et al., SIG Asia 2022) | Physics-based disassembly planning, 80+ parts | No. Unsolved assemblies are simply flagged. |
| Wang et al. (SIGGRAPH 2025) | RL-based multi-robot assembly with re-planning | No. "Alternative plans" = alternative *sequences*, not alternative *designs*. |
| Deuss et al. (SIG Asia 2014) | Sequencing for self-supporting masonry | No. Fixed geometry input; finds build order with temporary chains. |
| Parascho et al. (EPFL) | Scaffold-free assembly via cooperative robots | No. Uses robots as temporary supports; geometry is fixed. |

All five systems take geometry as given. When no feasible sequence exists, they either fail silently or report infeasibility without diagnostic information.

**Sources:** arXiv:2309.16909, ACM 10.1145/3550469.3555421, ACM 10.1145/3730824, GitHub repos for ASAP and Assemble-Them-All.

---

## Claim 2: Nobody closes the loop from planning failure to geometry repair

**Verdict: CONFIRMED, with nuance.**

No published system implements the loop: *plan fails → extract certificate → repair geometry → re-plan*.

**Near-misses that do NOT refute the claim:**

- **Structural form-finding** (BRG/ETH, Mueller/MIT): Optimizes geometry for final-state stability. Does not consider intermediate assembly states. Assembly sequencing is a separate downstream problem.

- **Topology optimization + assemblability** (Hirosawa 2023, Zhao/Wang 2023): These bake assemblability as a *constraint into initial optimization*, not as a *repair loop from failure*. Hirosawa's "assemblability" means collision-free part insertion directions (manufacturing DFM), not structural stability during construction. Zhao/Wang optimizes assembly *ordering* for a fixed frame structure, not geometry.

- **Design for Assembly (DfA)**: Boothroyd-Dewhurst and similar methods are scoring heuristics for human designers. No automated repair loop.

- **Scaffold synthesis** (Parascho et al.): Adds robot-held temporary supports, but does not modify the structure itself.

**The genuine gap:** Everyone either (a) plans for fixed geometry, or (b) optimizes geometry with assemblability as one constraint among many from scratch. Nobody starts from "this structure failed assembly planning" and asks "what is the minimum geometric change to make it pass?"

---

## Claim 3: Using Farkas certificates as geometry repair signals is novel

**Verdict: CONFIRMED, with one important near-miss.**

**The near-miss:** Wang et al., "Design and Structural Optimization of Topological Interlocking Assemblies" (SIGGRAPH Asia 2019) uses Farkas' lemma to *define* a stability measure for assemblies and optimizes geometry to maximize it. MOCCA (SIGGRAPH 2021) extends this to cone joints and considers intermediate assembly stages.

**Why this does not refute our claim:** These papers use Farkas' lemma as an *optimization objective* (maximize stability margin). They do not extract the Farkas certificate from an *infeasible* LP as a diagnostic signal pointing to *which contacts are insufficient* and *which direction to move vertices*. The distinction:
- Wang 2019: "maximize stability" (forward optimization)
- Ours: "this is infeasible → here's exactly why → here's the minimal fix" (diagnosis + repair)

**Targeted Scholar search** for `"Farkas" AND ("assembly" OR "masonry") AND ("repair" OR "modification")` returned zero results. The infeasibility-certificate-as-repair-gradient framing appears novel.

**Caveat:** Whiting et al. (2012) compute geometric sensitivities ∂A/∂p for masonry stability. We build on this — our contribution is connecting it to infeasibility certificates in the context of assembly sequence planning, not inventing the sensitivity computation itself.

---

## Claim 4: CEGIS applied to assembly planning is novel

**Verdict: CONFIRMED.**

No prior work applies CEGIS (Solar-Lezama's counterexample-guided inductive synthesis) to robotic assembly or construction sequencing. Checked PL venues (PLDI, POPL, CAV) and robotics venues (ICRA, RSS, IROS).

**Adjacent work:**
- TAMP (Task and Motion Planning) uses constraint-based search with backtracking, but is not framed as synthesis with a verifier-in-the-loop.
- Nedunuri et al. (2014) applied SMT-based synthesis to robot strategies, but for navigation, not assembly.
- Assembly planning traditionally uses AND/OR graphs, constraint satisfaction, or RL — not inductive synthesis.

---

## Claim 5: The CDCL analogy is technically sound

**Verdict: SOUND, with a known gap.**

- **Pruning power:** Each precedence constraint `A ≺ B` eliminates exactly half the permutations involving A and B. Multiple independent constraints compose multiplicatively — genuinely exponential pruning. Structurally parallel to CDCL clause learning.

- **The gap:** CDCL conflict clauses are *logically exact* (derived via resolution — the precise minimal reason for the conflict). Our precedence constraints are *sufficient but potentially conservative* — the LP identifies "A must support B" when the true requirement might be "A or C must support B." We learn the stronger constraint. This means our search may terminate earlier with INFEASIBLE than necessary.

- **Recommendation:** Acknowledge this in any writeup. The analogy is illuminating but not exact. Our "clauses" are sound but not guaranteed minimal.

---

## Claim 6: Form-finding ignores constructibility

**Verdict: MOSTLY CONFIRMED.**

BRG (ETH), Mueller (MIT), and mainstream tools optimize for final-state performance. Assembly sequence feasibility is not part of the optimization objective.

**Exception:** A small body of recent work (2023–2025) has begun coupling assembly constraints into topology optimization (Hirosawa 2023, Zhao/Wang 2023). However:
- These are isolated academic efforts, not mainstream
- They treat assemblability as a manufacturing constraint (insertion directions), not structural stability during sequential construction
- None use failure certificates for repair

**Corrected claim:** "Mainstream structural form-finding ignores sequential assembly feasibility. Recent academic work has begun adding assemblability constraints to topology optimization, but none implement a failure-diagnosis-repair loop."

---

## Summary

| Claim | Status | Key caveat |
|-------|--------|-----------|
| Existing planners = fixed geometry only | **Confirmed** | — |
| No planning-failure → geometry-repair loop | **Confirmed** | Near-misses exist but solve different problems |
| Farkas certificate for repair is novel | **Confirmed** | Wang 2019 uses Farkas for optimization (not repair); Whiting 2012 provides the sensitivity math we build on |
| CEGIS for assembly is novel | **Confirmed** | TAMP has backtracking but isn't framed as synthesis |
| CDCL analogy is sound | **Confirmed with caveat** | Our "clauses" are sound but not guaranteed minimal |
| Form-finding ignores constructibility | **Mostly confirmed** | Small 2023+ academic exceptions; none do repair |

**Overall assessment:** The core novelty claim — *using LP infeasibility certificates from failed assembly planning to guide minimal geometry repair* — holds up under scrutiny. The individual components (LP stability, CEGIS, geometric sensitivity) exist in the literature; the contribution is connecting them into a single loop.

---

*Verified April 2026. 15 research agents, cross-checked across 5 follow-up investigations.*
