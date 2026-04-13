"""Tests for the kinematic verifier and its integration with CEGIS."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root via `uv run pytest`
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest
from shapely.geometry import Polygon

from counterplan.geometry import Block, Structure
from counterplan.cegis import solve
from counterplan.verifiers import KinematicVerifier, StabilityVerifier
from counterplan.verifiers.kinematic import drop_corridor
from counterplan.structures import (
    wall_4, pyramid_6, pyramid_10, post_and_lintel_5,
    arch_5, gothic_arch_9, unstable_tower,
)


def _unit_square(bid: int, x: float, y: float, w: float = 1.0, h: float = 1.0) -> Block:
    return Block(id=bid, vertices=np.array([
        [x, y], [x + w, y], [x + w, y + h], [x, y + h],
    ]))


def test_drop_corridor_is_upward_prism():
    """Default direction (0,-1): corridor sweeps the block's polygon upward."""
    b = _unit_square(0, 0.0, 0.0)
    corr = drop_corridor(b)
    # Corridor should contain a point far above the block
    assert corr.contains(Polygon([[0.1, 10], [0.9, 10], [0.9, 11], [0.1, 11]]).centroid)
    # Corridor should NOT contain a point far below the block
    assert not corr.contains(Polygon([[0.1, -10], [0.9, -10], [0.9, -9], [0.1, -9]]).centroid)


def test_kinematic_blocker_above():
    """A block placed at (0, 2) blocks the descent of a block targeted at (0, 0)."""
    lower = _unit_square(0, 0.0, 0.0)
    upper = _unit_square(1, 0.0, 2.0)
    s = Structure(blocks=[lower, upper])

    v = KinematicVerifier()
    # Place upper first, then lower — lower's descent collides with upper.
    r = v.check(s, sequence=[1, 0], step=1, all_block_ids=[0, 1])
    assert not r.feasible
    assert r.new_constraints[0].before == 0
    assert r.new_constraints[0].after == 1
    assert r.new_constraints[0].source == "kinematic"


def test_kinematic_no_overlap_passes():
    """Two side-by-side blocks: placing either first doesn't block the other."""
    left = _unit_square(0, 0.0, 0.0)
    right = _unit_square(1, 2.0, 0.0)
    s = Structure(blocks=[left, right])

    v = KinematicVerifier()
    r = v.check(s, sequence=[0, 1], step=1, all_block_ids=[0, 1])
    assert r.feasible


def test_kinematic_edge_contact_ignored():
    """Blocks sharing a vertical edge aren't treated as blocking (zero overlap area)."""
    a = _unit_square(0, 0.0, 0.0)
    b = _unit_square(1, 1.0, 0.0)  # shares edge at x=1
    s = Structure(blocks=[a, b])

    v = KinematicVerifier()
    r = v.check(s, sequence=[0, 1], step=1, all_block_ids=[0, 1])
    assert r.feasible


def test_pyramid_6_feasible_with_full_chain():
    """pyramid_6 must remain feasible with stability + kinematic."""
    r = solve(pyramid_6(), max_rounds=50, seed=42)
    assert r.feasible
    assert r.sequence is not None
    # Every step must pass both verifiers
    assert all(s.feasible for rd in r.rounds for s in rd.steps if rd.failure_step is None)


def test_pyramid_10_feasible_and_uses_kinematic():
    """pyramid_10 is feasible, and CEGIS learns at least one kinematic constraint
    (it rules out orderings where a row-2 block is placed before a row-1 block
    beneath it)."""
    r = solve(pyramid_10(), max_rounds=100, seed=42)
    assert r.feasible
    has_kinematic = any(pc.source == "kinematic" for pc in r.constraints)
    assert has_kinematic, "expected at least one kinematic constraint in pyramid_10"


def test_pyramid_10_block_8_blocks_block_6_descent():
    """Direct regression: in pyramid_10, if block 8 (row-2 right, x=[0,1.5])
    is placed before block 6 (row-1 right, x=[0.75,2.25]), block 6's vertical
    drop corridor intersects block 8 over an area of 0.75. The kinematic
    verifier must catch this and learn 6 ≺ 8.
    """
    s = pyramid_10()
    v = KinematicVerifier()
    # Arbitrary prefix that places 8 before 6 is enough — verifier only looks
    # at `placed_before` for the step being checked.
    seq = [0, 1, 2, 3, 4, 5, 8, 6, 7, 9]
    r = v.check(s, sequence=seq, step=7, all_block_ids=[b.id for b in s.blocks])
    assert not r.feasible, "kinematic verifier must detect 8 blocks 6's descent"
    assert r.diagnostics["blockers"] == [8]
    assert len(r.new_constraints) == 1
    pc = r.new_constraints[0]
    assert (pc.before, pc.after, pc.source) == (6, 8, "kinematic")


def test_pyramid_10_final_sequence_respects_kinematic():
    """End-to-end: the CEGIS solution for pyramid_10 must place block 6
    before block 8 (since 8 otherwise blocks 6's vertical descent)."""
    r = solve(pyramid_10(), max_rounds=100, seed=42)
    assert r.feasible and r.sequence is not None
    idx6 = r.sequence.index(6)
    idx8 = r.sequence.index(8)
    assert idx6 < idx8, (
        f"block 6 must come before block 8 in the final sequence; got {r.sequence}"
    )


def test_wall_and_post_lintel_feasible():
    for sf in (wall_4, post_and_lintel_5):
        r = solve(sf(), max_rounds=50, seed=42)
        assert r.feasible, f"{sf.__name__} should be feasible"


def test_arches_infeasible():
    """Arch stability cycles should still dominate — arches remain INFEASIBLE."""
    for sf in (arch_5, gothic_arch_9):
        r = solve(sf(), max_rounds=50, seed=42)
        assert not r.feasible, f"{sf.__name__} should be infeasible"


def test_constraint_sources_tagged():
    """Every learned constraint carries a source tag."""
    r = solve(arch_5(), max_rounds=50, seed=42)
    for pc in r.constraints:
        assert pc.source in {"stability", "kinematic"}


def test_kinematic_direction_override():
    """Verifier direction can be customized (e.g., horizontal slide-in)."""
    a = _unit_square(0, 0.0, 0.0)
    b = _unit_square(1, 2.0, 0.0)  # b's target is to the right of a

    s = Structure(blocks=[a, b])

    # direction = (+1, 0) → b's motion is rightward; it approaches from -x.
    # Block a sits at x=0..1, inside b's approach corridor. Expect collision.
    v = KinematicVerifier(direction=(1.0, 0.0))
    r = v.check(s, sequence=[0, 1], step=1, all_block_ids=[0, 1])
    assert not r.feasible
    # And the opposite direction — b approaches from +x, a is not in the path.
    v2 = KinematicVerifier(direction=(-1.0, 0.0))
    r2 = v2.check(s, sequence=[0, 1], step=1, all_block_ids=[0, 1])
    assert r2.feasible


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
