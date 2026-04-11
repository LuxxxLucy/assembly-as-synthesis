"""JSON trace export for CEGIS assembly planning results.

Serializes CEGISResult + Structure into a JSON format consumable by
web-based visualizers. Each CEGIS round is a self-contained snapshot.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .geometry import Structure
from .cegis import CEGISResult
from .stability import check_stability


def export_trace(
    structure: Structure,
    cegis_result: CEGISResult,
    path: str,
    name: str = "",
) -> None:
    """Export a CEGIS trace to JSON.

    The trace contains:
      - Structure geometry (blocks with vertices)
      - CEGIS rounds (candidate sequences, failures, constraints)
      - Per-step stability margins
    """
    trace = {
        "name": name,
        "structure": _export_structure(structure),
        "result": {
            "feasible": cegis_result.feasible,
            "sequence": cegis_result.sequence,
            "total_rounds": len(cegis_result.rounds),
        },
        "rounds": [_export_round(rd, structure) for rd in cegis_result.rounds],
    }
    Path(path).write_text(json.dumps(trace, indent=2, default=_json_safe))


def _export_structure(structure: Structure) -> dict:
    return {
        "blocks": [
            {
                "id": b.id,
                "vertices": b.vertices.tolist(),
                "mass": b.mass,
                "centroid": b.centroid.tolist(),
            }
            for b in structure.blocks
        ],
        "ground_y": structure.ground_y,
    }


def _export_round(rd, structure: Structure) -> dict:
    steps = []
    for i, sr in enumerate(rd.stability_results):
        placed = rd.candidate[:i + 1]
        margin = sr.margin if math.isfinite(sr.margin) else (-1.0 if sr.margin < 0 else 1.0)
        step_data = {
            "step": i,
            "block": rd.candidate[i],
            "placed": placed,
            "stable": sr.feasible,
            "margin": margin,
        }
        if sr.block_margins:
            step_data["block_margins"] = {str(k): v for k, v in sr.block_margins.items()}
        steps.append(step_data)

    return {
        "round": rd.round_num,
        "candidate": rd.candidate,
        "failure_step": rd.failure_step,
        "failed_block": rd.failed_block,
        "steps": steps,
        "constraints_learned": [
            {"before": pc.before, "after": pc.after}
            for pc in rd.new_constraints
        ],
    }


def _json_safe(obj):
    """Handle non-JSON-serializable values."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
