# Assembly as Synthesis

Reframes robotic assembly sequence planning as program synthesis: a fixed physics verifier with a swappable proposer. Five proposers are compared on the same structure (`pyramid_10`) through the same CEGIS loop and the same verifier chain (kinematic / stability / landing).

**Blog (figures + interactive 3D viewer):** <https://luxxxlucy.github.io/assembly-as-synthesis/>

## Methods tested

| Proposer | What it sees | How it proposes |
|---|---|---|
| Random CEGIS | Nothing beyond the counterexample | Uniform random order, rejection-sampled against learned clauses |
| Z3 (SMT) | Full topology as SMT clauses | Complete search over permutations with learned blocking clauses |
| LLM-basic | Block adjacency only (no coordinates) | Text prompt, free-form reasoning |
| LLM-geometric | Block coordinates + layout | Text prompt with geometry |
| VLM | Labelled image of the target (labels permuted, no position text) | Vision-language model on the rendered scene |

All five share the verifier chain and the CEGIS skeleton; only the proposer and the encoding of its feedback change.

## Repo layout

- `src/counterplan/` — CEGIS core, verifiers, proposers (`z3_solver.py`, `llm_solver.py`, `vlm_solver.py`)
- `examples/run_experiments.py` — run the comparison
- `web/` — Three.js isometric viewer (Monument-Valley aesthetic)
- `index.html` + `blog.css` — the published blog
- `verify.md` — independent verification of the novelty claims
- `papers/` — related work

## Running

Requires `FIREWORKS_API_KEY` in the environment for the LLM and VLM proposers.

```bash
uv sync
uv run python examples/run_experiments.py
```
