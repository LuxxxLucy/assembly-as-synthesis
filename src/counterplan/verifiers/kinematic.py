"""Kinematic verifier: each block must be reachable along an insertion direction
without colliding with already-placed blocks.

The CEGIS stability check only ensures a block can *stand* at its final position.
A block also has to *get there*. Default assumption: blocks descend straight down
from y = +∞ (matching gravity-driven placement in the web demo).

For each block being placed at step k, we compute its *drop corridor* — the swept
volume of its polygon translated along the insertion direction to infinity. Any
already-placed block whose interior intersects that corridor is a blocker, and
the learned precedence is `B ≺ blocker` (flip the order so the blocker drops
in later, over the now-placed B).

This catches the classic arch-keystone case: neighbors are in the drop path, but
stability says neighbors must come first — a cycle that correctly signals
"needs scaffolding".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

from ..geometry import Block, Structure
from .base import Verifier, VerifierResult, PrecedenceConstraint


# Distance the block is swept along the insertion direction. Large enough to
# cover any realistic scene; polygon clipping is exact regardless.
SWEEP_LENGTH = 1000.0

# Area below which a corridor/block intersection is treated as grazing contact
# (shared edge or vertex), not collision.
OVERLAP_AREA_TOL = 1e-6


def drop_corridor(block: Block, direction: tuple[float, float] = (0.0, -1.0)) -> Polygon:
    """Swept volume of `block` translated along `-direction` to infinity.

    With default direction = (0, -1) (gravity), the corridor is the region the
    block occupies as it descends from y = +∞ to its final position — i.e. the
    block's polygon unioned with copies of itself shifted upward.

    We approximate "to infinity" with a single translated copy at SWEEP_LENGTH;
    taking the convex hull of the union is exact for convex blocks. For
    non-convex blocks we take the full union of many translated copies, but
    blocks in this system are convex in practice, so we use the hull.
    """
    insertion = -np.asarray(direction, dtype=float)  # direction of motion during placement
    norm = np.linalg.norm(insertion)
    if norm < 1e-12:
        raise ValueError("insertion direction must be non-zero")
    insertion = insertion / norm

    base = Polygon(block.vertices)
    shifted = Polygon(block.vertices + insertion * SWEEP_LENGTH)
    try:
        return unary_union([base, shifted]).convex_hull
    except Exception:
        # Shapely can choke on near-collinear hulls at extreme SWEEP_LENGTH.
        # Fallback: convex hull of the combined vertex set directly.
        pts = np.vstack([block.vertices, block.vertices + insertion * SWEEP_LENGTH])
        from shapely.geometry import MultiPoint
        return MultiPoint([tuple(p) for p in pts]).convex_hull


@dataclass
class KinematicVerifier:
    """Strict top-down (or arbitrary-direction) collision check."""

    name: str = "kinematic"
    direction: tuple[float, float] = (0.0, -1.0)  # gravity: block approaches from +y
    overlap_tol: float = OVERLAP_AREA_TOL

    # Optional per-block direction override: block_id -> (dx, dy)
    per_block_direction: dict[int, tuple[float, float]] = field(default_factory=dict)

    def _direction_for(self, block_id: int) -> tuple[float, float]:
        return self.per_block_direction.get(block_id, self.direction)

    def check(
        self,
        structure: Structure,
        sequence: list[int],
        step: int,
        all_block_ids: list[int],
    ) -> VerifierResult:
        placing_id = sequence[step]
        placed_before = sequence[:step]

        placing = structure.block_by_id(placing_id)
        corridor = drop_corridor(placing, self._direction_for(placing_id))

        blockers: list[int] = []
        for bid in placed_before:
            other = structure.block_by_id(bid)
            other_poly = Polygon(other.vertices)
            inter = corridor.intersection(other_poly)
            if not inter.is_empty and inter.area > self.overlap_tol:
                blockers.append(bid)

        diagnostics = {
            "direction": list(self._direction_for(placing_id)),
            "blockers": blockers,
        }

        if not blockers:
            return VerifierResult(
                verifier=self.name, feasible=True, diagnostics=diagnostics,
            )

        # Learn: placing_id must come before each blocker (flip the order so the
        # blocker descends later, over the already-placed placing_id).
        constraints = [
            PrecedenceConstraint(
                before=placing_id,
                after=bid,
                source=self.name,
                reason=f"{bid} blocks descent of {placing_id}",
            )
            for bid in blockers
        ]

        return VerifierResult(
            verifier=self.name,
            feasible=False,
            new_constraints=constraints,
            reason=f"block {placing_id} collides with {blockers} on descent",
            diagnostics=diagnostics,
        )
