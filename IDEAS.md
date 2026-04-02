
# Assembly as Synthesis
## Top Research Directions

> Aggregated from 30 ideas across 3 expert brainstorming passes  
> Formal Methods × ML Systems × Computational Design  
> Wang et al. SIGGRAPH 2025 × Solar-Lezama 2008 SKETCH/CEGIS

---

```
The unifying reframe:
┌─────────────────────────────────────────────────────────┐
│  DSL :  hold(part)  |  remove(part)                     │
│  Spec:  ∀ s ∈ trace . stability(s) = true               │
│  Task:  synthesize P satisfying Spec                    │
│                                                         │
│  beam search  →  sketch generator                       │
│  learned policy  →  hole filler                         │
│  failed assembly  →  counterexample                     │
└─────────────────────────────────────────────────────────┘
```

---

## ★ Rank #1 — CEGIS Assembly Loop

### *Counterexample-Guided Inductive Synthesis for Physical Assembly Planning*

```
         ┌──────────────────────────────────────────────┐
         │                  CEGIS LOOP                  │
         │                                              │
         │   Neural Policy ──plan P──► Physics Sim      │
         │       ▲                         │            │
         │       │         stable? ────────┘            │
         │       │           │                          │
         │       │          NO                          │
         │       │           │                          │
         │       └── CX ◄────┘                          │
         │       (minimal instability witness)           │
         └──────────────────────────────────────────────┘
```

**The core insight:**  
Wang et al.'s re-training problem *is* the synthesis gap in Solar-Lezama's CEGIS.  
Every collapsed arch is a **counterexample**. Every counterexample is a structured  
correction signal. CEGIS turns random RL exploration into *directed failure mining*.

**Technical contributions:**

| Component | What's new |
|---|---|
| **Witness extraction** | Binary-search over plan prefixes → minimal unstable sub-sequence |
| **Symbolic CX** | Lift concrete failure to equivalence class via contact graph topology — one CX covers a family of structures |
| **Convergence theory** | If hypothesis space is finite (bounded depth/branching), loop terminates; bound # CX classes per topology class |
| **Anti-unification** | Generalize single-structure CX to structure family via anti-unification on contact graphs |
| **Approximate oracle** | CEGIS with probabilistic verifier; correctness up to confidence bound |

**Why it's the #1 idea:**  
Three independent agents converged on this. It is the *cleanest* intellectual bridge between  
the PL and robotics communities — no new infrastructure needed, just a loop connecting  
existing pieces (Wang et al. policy + physics sim + counterexample extractor). It is both  
theoretically principled and immediately implementable.

**The pitch in one sentence:**  
> "We replace Wang et al.'s undirected RL curriculum with a formal CEGIS loop — every  
> failed assembly becomes a symbolic counterexample that drives precisely targeted retraining."

**Demo:** Policy trained on 5-stone arch generalizes to 20-stone vault in 10× fewer  
simulation calls than PPO baseline. Convergence curve shows counterexample classes saturating.

---

## ★ Rank #2 — AssemblyML: A Type System for Buildability

### *Dependent Types Where the Type IS the Physics Verifier*

```
  AssemblyML Type Theory
  ─────────────────────────────────────────────────────

  Base types:    Part   Config   Robot

  Refinement:    StableConfig = { c : Config | ⊨ stable(c) }
                               └── LP feasibility check ──┘

  Linear types:  hold : Part ⊸ HeldPart        (must release exactly once)
                 release : HeldPart ⊸ Part      (no double-release, no leak)

  Plan type:     P : StableAssembly(S, k)
                 ≡ proof that executing P on structure S
                   maintains stability margin ≥ k at every step

  Type checking  ≡  stability verification
  Type error     ≡  collapse prediction
  Type synthesis ≡  plan synthesis
```

**The Curry-Howard correspondence for physical structures:**

```
  Program       ↔   Assembly plan
  Type          ↔   Stability invariant
  Proof         ↔   Certificate of buildability
  Type error    ↔   Predicted collapse
  Proof search  ↔   Plan synthesis
```

**Technical contributions:**

| Challenge | Approach |
|---|---|
| **Decidability** | Restrict stability predicate to linear-arithmetic statics (LP feasibility) — computable in polynomial time |
| **Soundness** | Every well-typed plan is physically safe; type system is conservative approximation of full physics |
| **Linear discipline** | `hold` operations typed with linear logic — mirrors session types and resource logic |
| **Proof-carrying plans** | Ship plans with stability certificates; verifier at deployment is a type checker, not a simulator |
| **Bidirectional checking** | Elaborate partial plans into full type-correct terms — type checker becomes plan synthesizer |

**Why it earns #2:**  
The intellectual move — *embedding a continuous physics predicate into a decidable type theory* —  
is genuinely novel. No assembly planner has been framed this way. It imports the entire  
PL/FM toolbox (type inference, proof assistants, certified compilation) into structural mechanics.  
A senior PL researcher would call it a foundational contribution.

**The pitch in one sentence:**  
> "We define AssemblyML, a dependent type theory where a well-typed plan *is* a proof  
> of buildability — turning collapse prediction into type checking and plan synthesis  
> into proof search."

**Demo:** An interactive type-checker for assembly plans. Red underlines = predicted  
collapse points. Tab-completion = synthesis. Export plan + certificate for robot execution.

---

## ★ Rank #3 — PhysicsGrammar: Generative Design of Robot-Native Architecture

### *Synthesizability as a Differentiable Design Objective*

```
   Traditional:   Structure → Find assembly plan
   PhysicsGrammar: Assembly capability → Generate novel structures

   ┌─────────────────────────────────────────────────────┐
   │                                                     │
   │   Geometry params θ ──► Structure S(θ)              │
   │                              │                      │
   │                              ▼                      │
   │                   Synthesizability(S(θ))             │
   │                   = P(valid plan found in budget)   │
   │                              │                      │
   │                         ∂/∂θ │  ← smooth approx     │
   │                              │                      │
   │                         Gradient ascent             │
   │                              │                      │
   │                              ▼                      │
   │           Novel forms no human would design —       │
   │           optimized for a robot team's specific     │
   │           mechanical capabilities                   │
   └─────────────────────────────────────────────────────┘
```

**Output: A Pareto frontier**

```
  Aesthetic quality
       ▲
     ● │          ●
       │    ●  ●
     ● │  ●
       │●
       └──────────────► Synthesizability (robot buildability)
       
  Each point = a family of novel architectural forms
  guaranteed buildable by the target robot team
```

**Technical contributions:**

| Component | What's new |
|---|---|
| **Differentiable synthesizability** | Smooth approximation of combinatorial search success probability via learned value function |
| **Constrained geometry optimization** | Stays in physically meaningful space (rigid parts, valid contacts) during gradient steps |
| **Style discriminator** | Aesthetic quality = learned discriminator vs. corpus of historical masonry |
| **Robot-native forms** | Output structures exploit robot team's specific reach/hold capabilities — not constrained by human ergonomics |
| **Discovery guarantee** | Structures on the Pareto frontier are provably unreachable by human-centered design processes |

**Why it earns #3:**  
This is the most visually spectacular idea — it produces *new architectural forms* as output.  
It inverts the entire problem (design → plan → execute → repeat) into a single differentiable  
loop. The resulting forms look alien and beautiful, immediately compelling for a SIGGRAPH paper  
or public demo. It also makes the strongest claim: *the synthesis algorithm is not just a  
planner — it is a design oracle.*

**The pitch in one sentence:**  
> "We invert assembly planning: instead of finding how to build a given structure, we use  
> synthesizability as a differentiable objective to discover novel architectural forms that  
> only a robot team could build."

**Demo:** Side-by-side of human-designed arch vs. PhysicsGrammar arch. Both stand.  
The PhysicsGrammar arch looks like nothing in history. Robot team builds both.  
Time-lapse video. This is the paper cover image.

---

## Aggregation Notes

| Idea | FM | ML | VIS | Score |
|---|---|---|---|---|
| CEGIS Assembly Loop | ★★★ | ★★★ | ★★ | **9** |
| AssemblyML Type System | ★★★ | ★ | ★★ | **7** |
| PhysicsGrammar | ★ | ★★ | ★★★ | **7** |
| SketchFill / ArchitectSketch | ★★ | ★★ | ★★★ | **7** |
| Library Learning (DreamAssembler) | ★★★ | ★★★ | ★★ | **8** |
| Amortized / Equivariant Policy | ★ | ★★★ | ★ | **5** |
| AssemblyAR | ★ | ★ | ★★★ | **5** |

> Library Learning (DreamAssembler) narrowly missed #3 — it is excellent but  
> slightly less visually novel than PhysicsGrammar. Pursue as a companion paper  
> or Chapter 2 after CEGIS is established.

---

## Research Agenda (Natural Ordering)

```
Phase 1 ─── CEGIS Assembly Loop ─────────────────── 6 months
             Establish formal connection to Solar-Lezama.
             Show counterexample convergence on arch family.
             Target: ICLR / ICRA / SIGGRAPH

Phase 2 ─── AssemblyML Type System ──────────────── 12 months
             Build on Phase 1 stability certificates.
             Formalize type theory, prove soundness.
             Target: PLDI / POPL

Phase 3 ─── PhysicsGrammar ──────────────────────── 18 months
             Use Phase 1 synthesizer as oracle.
             Differentiable loop over geometry.
             Target: SIGGRAPH (cover paper candidate)
```

---

*Sources: 30 ideas from 3 parallel sonnet brainstorm agents · March 2026*  
*Paper: Wang et al. SIGGRAPH 2025, DOI 10.1145/3730824*  
*Theory: Solar-Lezama 2008, Program Synthesis by Sketching*
