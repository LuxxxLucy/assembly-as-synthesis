"""JSON trace export — the one bridge between algorithm and visualization.

The trace is a self-describing snapshot of a CEGIS run: structure geometry,
every round's candidate sequence, per-step verifier results, and the final
outcome. The web viewer consumes this JSON and knows nothing about the solver.

Schema (versioned):
  {
    "schema": "counterplan-trace/2",
    "name": str,
    "structure": { blocks[], ground_y, extents },
    "result":    { feasible, sequence, total_rounds },
    "rounds":    [{ round, candidate, failure_step, failed_block,
                    failed_verifier, steps[], constraints_learned[] }]
  }
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .geometry import Block, Structure
from .cegis import CEGISResult


SCHEMA_VERSION = "counterplan-trace/2"


def export_trace(
    structure: Structure,
    cegis_result: CEGISResult,
    path: str,
    name: str = "",
) -> None:
    trace = {
        "schema": SCHEMA_VERSION,
        "name": name,
        "structure": _export_structure(structure),
        "result": {
            "feasible": cegis_result.feasible,
            "sequence": cegis_result.sequence,
            "total_rounds": len(cegis_result.rounds),
        },
        "rounds": [_export_round(rd) for rd in cegis_result.rounds],
    }
    Path(path).write_text(json.dumps(trace, indent=2, default=_json_safe))


def _export_structure(structure: Structure) -> dict:
    xs = [v[0] for b in structure.blocks for v in b.vertices]
    ys = [v[1] for b in structure.blocks for v in b.vertices]
    extents = {
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
    }
    return {
        "blocks": [_export_block(b) for b in structure.blocks],
        "ground_y": structure.ground_y,
        "extents": extents,
    }


def _export_block(b: Block) -> dict:
    depth = getattr(b, "depth", 1.0)
    return {
        "id": b.id,
        "vertices": b.vertices.tolist(),
        "centroid": b.centroid.tolist(),
        "mass": b.mass,
        "depth": depth,
    }


def _export_round(rd) -> dict:
    return {
        "round": rd.round_num,
        "candidate": rd.candidate,
        "failure_step": rd.failure_step,
        "failed_block": rd.failed_block,
        "failed_verifier": rd.failed_verifier,
        "steps": [_export_step(s) for s in rd.steps],
        "constraints_learned": [
            {
                "before": pc.before,
                "after": pc.after,
                "source": pc.source,
                "reason": pc.reason,
            }
            for pc in rd.new_constraints
        ],
    }


def _export_step(step) -> dict:
    return {
        "step": step.step,
        "block": step.block,
        "feasible": step.feasible,
        "failed_verifier": step.failed_verifier,
        "verifiers": [_export_verifier_result(vr) for vr in step.verifier_results],
    }


def _export_verifier_result(vr) -> dict:
    return {
        "verifier": vr.verifier,
        "feasible": vr.feasible,
        "reason": vr.reason,
        "diagnostics": _sanitize(vr.diagnostics),
    }


def _sanitize(obj):
    """Make diagnostics JSON-safe (numpy arrays, inf/nan, etc.)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return _sanitize(obj.tolist())
        if isinstance(obj, (np.integer, np.floating)):
            return _sanitize(obj.item())
    except ImportError:
        pass
    return obj


def _json_safe(obj):
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
    except ImportError:
        pass
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
