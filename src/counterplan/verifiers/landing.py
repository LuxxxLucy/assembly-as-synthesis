"""Landing verifier: after placement, the block must actually settle at its target.

Even if the fall path is clear (kinematic) and forces balance at target (equilibrium),
we still want to assert that the target is where the block physically rests — i.e.
*something* exists directly below it that would stop its descent. A block placed in
empty air would theoretically satisfy an LP with zero contact forces only if you
discount the constraint that ∑ vertical forces must balance gravity; in practice
the LP catches this, but a cheap geometric "is there something below?" check is a
useful independent sanity pass. Per the user: simple and stupid is fine.

Test: translate the block down by a small ε. If the translated block intrudes into
the ground or an already-placed block, then the target is supported → pass. If the
translated block sits in empty space, the block would fall past the target → fail.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon, box

from ..geometry import Block, Structure
from .base import Verifier, VerifierResult, PrecedenceConstraint


LANDING_PROBE_EPSILON = 1e-3


def _ground_polygon(ground_y: float, x_range: tuple[float, float]) -> Polygon:
    """A thick slab representing the ground below ground_y, spanning x_range."""
    lo, hi = x_range
    return box(lo - 10.0, ground_y - 1000.0, hi + 10.0, ground_y)


@dataclass
class LandingVerifier:
    name: str = "landing"
    direction: tuple[float, float] = (0.0, -1.0)  # descent direction (gravity)
    epsilon: float = LANDING_PROBE_EPSILON

    def check(
        self,
        structure: Structure,
        sequence: list[int],
        step: int,
        all_block_ids: list[int],
    ) -> VerifierResult:
        block_id = sequence[step]
        placed_before = sequence[:step]
        block = structure.block_by_id(block_id)

        # Probe: translate block a small ε in the descent direction.
        d = np.asarray(self.direction, dtype=float)
        d = d / np.linalg.norm(d)
        probe = Polygon(block.vertices + d * self.epsilon)

        xs = block.vertices[:, 0]
        ground = _ground_polygon(structure.ground_y, (float(xs.min()), float(xs.max())))

        # Any intersection area = support exists beneath target.
        if probe.intersection(ground).area > 1e-9:
            return VerifierResult(
                verifier=self.name, feasible=True,
                diagnostics={"support": "ground"},
            )

        for bid in placed_before:
            other = Polygon(structure.block_by_id(bid).vertices)
            if probe.intersection(other).area > 1e-9:
                return VerifierResult(
                    verifier=self.name, feasible=True,
                    diagnostics={"support": bid},
                )

        # No support directly beneath. Learn: any absent neighbor below block
        # could provide support — same directional filter used by stability.
        block_bottom = float(block.vertices[:, 1].min())
        placed_set = set(placed_before)
        all_contacts = structure.detect_contacts(all_block_ids)

        below_absent: set[int] = set()
        for c in all_contacts:
            for self_side, other_side in ((c.block_a, c.block_b), (c.block_b, c.block_a)):
                if self_side != block_id or other_side < 0 or other_side in placed_set:
                    continue
                other = structure.block_by_id(other_side)
                if other.vertices[:, 1].max() <= block_bottom + 1e-3:
                    below_absent.add(other_side)

        constraints = [
            PrecedenceConstraint(
                before=nb, after=block_id,
                source=self.name,
                reason=f"{nb} must land before {block_id} (support at target)",
            )
            for nb in sorted(below_absent)
        ]

        return VerifierResult(
            verifier=self.name,
            feasible=False,
            new_constraints=constraints,
            reason=f"block {block_id} has no support directly below target",
            diagnostics={"below_absent": sorted(below_absent)},
        )
