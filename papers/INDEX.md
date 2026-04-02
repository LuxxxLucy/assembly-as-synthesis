# Assembly as Synthesis — Paper Index

## Core Paper

### Wang et al. 2025 — Learning to Assemble with Alternative Plans
- **Venue:** ACM Transactions on Graphics (SIGGRAPH 2025), Vol 44 Issue 4
- **Authors:** Ziqi Wang, Wenjun Liu, Jingwen Wang, Gabriel Vallat, Fan Shi, Stefana Parascho, Maryam Kamgarpour
- **DOI:** 10.1145/3730824
- **Summary:** RL framework for assembling rigid-part structures (masonry buildings, bridges) using multiple robots that hold parts in place — eliminating dense scaffolding. Action space: `hold(part)`, `remove(part)`. Policy trained to find assembly sequences where every intermediate state is physically stable.
- **Problem:** Had to re-train per structure; fails on large search spaces.
- **Relevance:** This is the target system. Assembly as Synthesis re-frames its planning problem as program synthesis over a DSL.

---

## Program Synthesis Foundations

### Solar-Lezama 2008 — Program Synthesis by Sketching
- **Venue:** PhD Thesis, UC Berkeley (EECS-2008-176)
- **PDF:** https://people.csail.mit.edu/asolar/papers/thesis.pdf
- **Summary:** Introduced SKETCH and the CEGIS (Counterexample-Guided Inductive Synthesis) loop: a SAT-based inductive synthesizer paired with a bounded model-checker that generates counterexamples. Programmer writes a "sketch" (partial program), CEGIS fills in the holes.
- **Key insight:** The programmer's high-level strategy + automated low-level completion = tractable synthesis.
- **Relevance:** The beam-search in Wang 2025 generates a partial plan ("sketch"); the learned policy fills holes. CEGIS loop → curriculum: counterexamples from failed assemblies drive policy improvement.

---

## Assembly as Synthesis Framing

```
DSL:   hold(part) | remove(part)
Spec:  ∀ intermediate state s: stability(s) = true
Goal:  synthesize program P = [op₁, op₂, ..., opₙ] satisfying spec
```

**Connection to sketch synthesis:** beam search = sketch generator; policy = hole filler  
**CEGIS curriculum:** failed assemblies = counterexamples → retarget training data  
**Library learning:** compress successful plans into reusable sub-assembly primitives  

