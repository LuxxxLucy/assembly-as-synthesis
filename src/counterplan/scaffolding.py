"""Scaffolding synthesis for structures with cyclic assembly dependencies.

When CEGIS detects that no feasible assembly order exists (cyclic precedence
constraints), scaffolding synthesis adds temporary support blocks that break
the cycle. The key insight: arches and similar structures are stable when
complete but cannot be built sequentially without temporary centering.

Algorithm (CEGIS-squared):
  Outer loop: synthesize scaffold configurations
  Inner loop: existing CEGIS — test if augmented structure is assemblable
  Verification: completed structure is self-supporting without scaffolds

This mirrors real masonry construction: arches use centering (wooden formwork)
during construction, which is removed once the keystone is placed.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field

from .geometry import Block, Structure
from .stability import check_stability
from .cegis import solve as cegis_solve, CEGISResult


SCAFFOLD_ID_BASE = 1000  # Reserved ID range for scaffold blocks


@dataclass
class ScaffoldResult:
    """Result of scaffolding synthesis."""
    success: bool
    original_structure: Structure
    scaffolded_structure: Structure | None = None
    scaffold_blocks: list[Block] = field(default_factory=list)
    assembly_sequence: list[int] | None = None   # includes scaffold placement
    removal_order: list[int] | None = None        # order to remove scaffolds
    removal_stable: bool = False                   # structure stable after removal
    cegis_result: CEGISResult | None = None        # inner CEGIS trace


def synthesize_scaffolding(
    structure: Structure,
    cegis_result: CEGISResult,
    max_scaffolds: int = 3,
    max_cegis_rounds: int = 100,
    friction: float = 0.7,
    seed: int | None = None,
) -> ScaffoldResult:
    """Synthesize temporary support blocks for an infeasible structure.

    Strategy:
      1. Identify blocks involved in cyclic constraints
      2. For each cycle block, generate a candidate scaffold (vertical column
         from ground to block's underside)
      3. Add scaffolds to structure, re-run CEGIS
      4. Verify the completed structure (without scaffolds) is self-supporting
      5. If not, try adding more scaffolds

    Returns ScaffoldResult with the augmented structure, sequence, and
    scaffold removal info.
    """
    if cegis_result.feasible:
        return ScaffoldResult(success=True, original_structure=structure)

    # Find blocks in cyclic constraints
    cycle_blocks = _find_cycle_blocks(cegis_result)
    if not cycle_blocks:
        return ScaffoldResult(success=False, original_structure=structure)

    # Try increasing numbers of scaffolds
    block_ids = [b.id for b in structure.blocks]

    for n_scaffolds in range(1, max_scaffolds + 1):
        # Generate scaffold candidates for cycle blocks
        scaffold_sets = _generate_scaffold_sets(structure, cycle_blocks, n_scaffolds)

        for scaffolds in scaffold_sets:
            # Build augmented structure
            augmented = Structure(
                blocks=list(structure.blocks) + scaffolds,
                ground_y=structure.ground_y,
            )

            # Inner CEGIS: can we assemble the augmented structure?
            inner_result = cegis_solve(
                augmented, max_rounds=max_cegis_rounds,
                seed=seed, friction=friction,
            )

            if not inner_result.feasible:
                continue

            # Verify removal: is the original structure stable without scaffolds?
            scaffold_ids = {s.id for s in scaffolds}
            main_sequence = [b for b in inner_result.sequence if b not in scaffold_ids]
            removal_result = check_stability(
                structure, main_sequence, friction=friction,
            )

            return ScaffoldResult(
                success=True,
                original_structure=structure,
                scaffolded_structure=augmented,
                scaffold_blocks=scaffolds,
                assembly_sequence=inner_result.sequence,
                removal_order=[s.id for s in scaffolds],
                removal_stable=removal_result.feasible,
                cegis_result=inner_result,
            )

    return ScaffoldResult(success=False, original_structure=structure)


def _find_cycle_blocks(cegis_result: CEGISResult) -> list[int]:
    """Find blocks involved in cyclic precedence constraints.

    A cycle exists when both A≺B and B≺A (or longer chains) appear
    in the constraint set. These blocks need scaffolding support.
    """
    # Build adjacency from constraints
    forward: dict[int, set[int]] = {}
    for pc in cegis_result.constraints:
        forward.setdefault(pc.before, set()).add(pc.after)

    # Find all blocks that participate in any cycle
    cycle_blocks = set()
    all_nodes = set(forward.keys())
    for pc in cegis_result.constraints:
        all_nodes.add(pc.after)

    for start in all_nodes:
        # BFS/DFS from start — if we reach start again, it's in a cycle
        visited = set()
        stack = list(forward.get(start, set()))
        while stack:
            node = stack.pop()
            if node == start:
                cycle_blocks.add(start)
                break
            if node not in visited:
                visited.add(node)
                stack.extend(forward.get(node, set()))

    return sorted(cycle_blocks)


def _generate_scaffold_sets(
    structure: Structure,
    cycle_blocks: list[int],
    n_scaffolds: int,
) -> list[list[Block]]:
    """Generate candidate scaffold configurations.

    For each cycle block, create a vertical column from ground to the block's
    underside. This is the simplest scaffolding — a single column directly
    beneath the unsupported block.
    """
    candidates = []

    # Generate one scaffold per cycle block
    single_scaffolds = []
    for i, bid in enumerate(cycle_blocks):
        block = structure.block_by_id(bid)
        if block is None:
            continue

        # Column geometry: centered under the block, from ground to block bottom
        cx = block.centroid[0]
        bottom_y = block.vertices[:, 1].min()
        col_width = 0.5  # narrow support column

        scaffold = Block(
            id=SCAFFOLD_ID_BASE + i,
            vertices=np.array([
                [cx - col_width / 2, structure.ground_y],
                [cx + col_width / 2, structure.ground_y],
                [cx + col_width / 2, bottom_y],
                [cx - col_width / 2, bottom_y],
            ]),
            mass=5.0,  # heavy scaffold for stability
        )
        single_scaffolds.append(scaffold)

    # For n_scaffolds=1, try each single scaffold
    if n_scaffolds == 1:
        for s in single_scaffolds:
            candidates.append([s])
    else:
        # For n_scaffolds>1, try combinations
        from itertools import combinations
        for combo in combinations(single_scaffolds, min(n_scaffolds, len(single_scaffolds))):
            candidates.append(list(combo))

    return candidates
