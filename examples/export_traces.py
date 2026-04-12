#!/usr/bin/env python3
"""Export CEGIS traces for every built-in structure into web/data/*.json.

The web viewer consumes these JSON files directly. This script is the only
bridge between algorithm and visualization — keep it thin.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from counterplan.cegis import solve
from counterplan.trace import export_trace
from counterplan.structures import (
    wall_4, pyramid_6, pyramid_10, post_and_lintel_5,
    arch_5, arch_7, gothic_arch_9, unstable_tower, cantilever_5,
)


DEMOS = {
    "wall_4": wall_4,
    "pyramid_6": pyramid_6,
    "pyramid_10": pyramid_10,
    "post_and_lintel": post_and_lintel_5,
    "arch_5": arch_5,
    "arch_7": arch_7,
    "gothic_arch": gothic_arch_9,
    "unstable_tower": unstable_tower,
    "cantilever_5": cantilever_5,
}


def main() -> None:
    out_dir = ROOT / "web" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    for slug, factory in DEMOS.items():
        s = factory()
        result = solve(s, max_rounds=200, seed=42)
        path = out_dir / f"{slug}.json"
        export_trace(s, result, str(path), name=slug)

        kin = sum(1 for pc in result.constraints if pc.source == "kinematic")
        stab = sum(1 for pc in result.constraints if pc.source == "stability")
        land = sum(1 for pc in result.constraints if pc.source == "landing")
        status = "FEASIBLE" if result.feasible else "INFEASIBLE"
        print(f"{slug:20s} {status:10s} rounds={len(result.rounds):3d} "
              f"kin={kin} stab={stab} land={land}  →  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
