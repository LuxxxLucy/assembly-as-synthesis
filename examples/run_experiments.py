"""Run every proposer on pyramid_10 (the blog's single demo task).

Emits web/data/experiments.json with a `runs` list, one entry per proposer,
each giving `score_per_round` = best-so-far fraction of blocks placed before
the first verifier failure. The blog's comparison chart reads this.

Also emits web/data/z3_trace.json (clauses grown per round) for the Z3 panel.
"""

from __future__ import annotations
import json
import os
import sys
import time
sys.path.insert(0, 'src')

from counterplan.structures import pyramid_10
from counterplan.cegis import solve as solve_random
from counterplan.z3_solver import solve_z3


def score_round(rnd, n: int) -> float:
    if not rnd.candidate:
        return 0.0
    if rnd.failure_step is None:
        return 1.0
    return rnd.failure_step / n


def best_so_far(rounds, n: int) -> list[float]:
    trace, best = [], 0.0
    for r in rounds:
        best = max(best, score_round(r, n))
        trace.append(best)
    return trace


def run_random(structure, max_rounds, seed):
    t = time.time()
    result = solve_random(structure, max_rounds=max_rounds, seed=seed)
    n = len(structure.blocks)
    return {
        "label": "Random CEGIS",
        "color": "#9ca3af",
        "feasible": result.feasible,
        "n_rounds": len(result.rounds),
        "seconds": time.time() - t,
        "score_per_round": best_so_far(result.rounds, n),
        "final_plan": result.sequence,
    }


def run_z3(structure, max_rounds, seed):
    t = time.time()
    result, trace = solve_z3(structure, max_rounds=max_rounds, seed=seed)
    n = len(structure.blocks)
    z3_trace = [
        {"round_num": tr.round_num, "proposed_plan": tr.proposed_plan,
         "new_clauses": tr.new_clauses, "total_clauses": tr.total_clauses}
        for tr in trace
    ]
    with open("web/data/z3_trace.json", "w") as f:
        json.dump(z3_trace, f, indent=2)
    return {
        "label": "Z3 (SMT) CEGIS",
        "color": "#4e79a7",
        "feasible": result.feasible,
        "n_rounds": len(result.rounds),
        "seconds": time.time() - t,
        "score_per_round": best_so_far(result.rounds, n),
        "final_plan": result.sequence,
    }


def _dump_trace(name, result, trace):
    """Write a self-contained per-run JSON trace next to experiments.json."""
    rounds = [
        {"round": r.round_num, "plan": r.candidate,
         "failure_step": r.failure_step, "failed_block": r.failed_block,
         "failed_verifier": r.failed_verifier,
         "learned_constraints": [
             {"before": pc.before, "after": pc.after, "source": pc.source}
             for pc in r.new_constraints
         ]}
        for r in result.rounds
    ]
    llm_turns = [
        {"round": tr.round_num, "plan": tr.plan,
         "verifier_message": tr.verifier_message}
        for tr in trace
    ]
    with open(f"web/data/run_{name}.json", "w") as f:
        json.dump({"rounds": rounds, "llm_turns": llm_turns,
                   "final_plan": result.sequence}, f, indent=2)


def run_llm(structure, max_rounds, description_mode, label, color, tag, model=None):
    if not os.environ.get("FIREWORKS_API_KEY"):
        return {"label": label, "color": color, "skipped": "no FIREWORKS_API_KEY"}
    from counterplan.llm_solver import solve_llm, LLM_MODEL
    t = time.time()
    result, trace = solve_llm(
        structure, max_rounds=max_rounds,
        description_mode=description_mode, permute_ids=True,
        model=model or LLM_MODEL,
    )
    elapsed = time.time() - t
    _dump_trace(tag, result, trace)
    n = len(structure.blocks)
    return {
        "label": label,
        "color": color,
        "feasible": result.feasible,
        "n_rounds": len(result.rounds),
        "seconds": elapsed,
        "score_per_round": best_so_far(result.rounds, n),
        "final_plan": result.sequence,
        "trace_file": f"data/run_{tag}.json",
        "model": model or LLM_MODEL,
    }


def run_vlm(structure, max_rounds):
    if not os.environ.get("FIREWORKS_API_KEY"):
        return {"label": "VLM (image)",
                "color": "#e15759",
                "skipped": "no FIREWORKS_API_KEY"}
    from counterplan.vlm_solver import solve_vlm, VLM_MODEL
    t = time.time()
    os.makedirs("web/data", exist_ok=True)
    result, trace = solve_vlm(
        structure, max_rounds=max_rounds,
        save_png_to="web/data/pyramid_10_vlm_input.png",
    )
    elapsed = time.time() - t
    _dump_trace("vlm", result, trace)
    n = len(structure.blocks)
    return {
        "label": "VLM (image + tool)",
        "color": "#e15759",
        "feasible": result.feasible,
        "n_rounds": len(result.rounds),
        "seconds": elapsed,
        "score_per_round": best_so_far(result.rounds, n),
        "final_plan": result.sequence,
        "trace_file": "data/run_vlm.json",
        "model": VLM_MODEL,
    }


if __name__ == "__main__":
    structure = pyramid_10()
    n = len(structure.blocks)

    os.makedirs("web/data", exist_ok=True)

    runs = []
    # Classical proposers: cheap, run every time.
    runs.append(run_random(structure, max_rounds=30, seed=42))
    runs.append(run_z3(structure, max_rounds=30, seed=42))

    # LLM proposers (basic = no geometric prose; geometric = with layout).
    runs.append(run_llm(structure, 30, "basic",
                        "LLM (basic prose)", "#f4a261", tag="llm_basic"))
    runs.append(run_llm(structure, 30, "geometric",
                        "LLM (geometric prose)", "#59a14f", tag="llm_geom"))

    # VLM proposer (image + tool).
    runs.append(run_vlm(structure, 30))

    out = {"benchmark": "pyramid_10", "n_blocks": n, "runs": runs}
    with open("web/data/experiments.json", "w") as f:
        json.dump(out, f, indent=2)

    # Also emit a plain-JS bundle so the blog works when opened via file://
    # (Safari blocks fetch() from file://, so JSON-over-fetch fails there).
    with open("web/data/experiments.json") as f:
        experiments_blob = f.read()
    with open("web/data/z3_trace.json") as f:
        z3_blob = f.read()
    with open("web/data/data.js", "w") as f:
        f.write(
            "// Auto-generated by examples/run_experiments.py — do not edit.\n"
            f"window.EXPERIMENTS = {experiments_blob};\n"
            f"window.Z3_TRACE   = {z3_blob};\n"
        )

    print("Wrote web/data/experiments.json and web/data/data.js")
    for run in out["runs"]:
        if run.get("skipped"):
            print(f"  {run['label']}: SKIPPED ({run['skipped']})")
        else:
            s = run["score_per_round"]
            print(f"  {run['label']}: feasible={run['feasible']} "
                  f"rounds={run['n_rounds']} "
                  f"final_score={s[-1] if s else 0:.2f} "
                  f"time={run['seconds']:.1f}s")
