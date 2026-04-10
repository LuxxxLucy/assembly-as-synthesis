"""Pre-built test structures for demos and testing."""

from __future__ import annotations

import numpy as np

from .geometry import Block, Structure


def _parametric_arch(n_voussoirs: int, span: float, rise: float, thickness: float,
                     abutment_height: float = 2.0) -> Structure:
    """Generate a parametric semicircular arch with proper shared edges.

    Blocks are numbered: 0=right abutment, 1=left abutment, 2..n-1=voussoirs (right to left),
    last=keystone.

    The arch intrados (inner curve) is a circular arc. Voussoir joints are radial lines,
    so adjacent blocks always share a full edge.
    """
    # Arc center and radius
    cx, cy = 0.0, abutment_height
    R_inner = span / 2  # inner radius
    R_outer = R_inner + thickness

    # Divide the arc into n_voussoirs equal angular segments
    # Angle 0 = right springing, angle pi = left springing
    angles = np.linspace(0, np.pi, n_voussoirs + 1)

    blocks = []

    # Abutments
    abut_width = thickness * 1.2
    # Right abutment (id=0): sits under the right springing point
    r_inner_x = cx + R_inner * np.cos(angles[0])
    r_outer_x = cx + R_outer * np.cos(angles[0])
    blocks.append(Block(id=0, vertices=np.array([
        [r_inner_x, 0.0],
        [r_outer_x + abut_width * 0.3, 0.0],
        [r_outer_x + abut_width * 0.3, abutment_height],
        [r_inner_x, abutment_height],
    ]), mass=2.0))

    # Left abutment (id=1): sits under the left springing point
    l_inner_x = cx + R_inner * np.cos(angles[-1])
    l_outer_x = cx + R_outer * np.cos(angles[-1])
    blocks.append(Block(id=1, vertices=np.array([
        [l_outer_x - abut_width * 0.3, 0.0],
        [l_inner_x, 0.0],
        [l_inner_x, abutment_height],
        [l_outer_x - abut_width * 0.3, abutment_height],
    ]), mass=2.0))

    # Voussoirs (id=2..n_voussoirs+1)
    for i in range(n_voussoirs):
        a0 = angles[i]
        a1 = angles[i + 1]

        # Four corners: inner-right, outer-right, outer-left, inner-left
        ir = np.array([cx + R_inner * np.cos(a0), cy + R_inner * np.sin(a0)])
        or_ = np.array([cx + R_outer * np.cos(a0), cy + R_outer * np.sin(a0)])
        ol = np.array([cx + R_outer * np.cos(a1), cy + R_outer * np.sin(a1)])
        il = np.array([cx + R_inner * np.cos(a1), cy + R_inner * np.sin(a1)])

        blocks.append(Block(
            id=i + 2,
            vertices=np.array([ir, or_, ol, il]),
            mass=1.0,
        ))

    return Structure(blocks=blocks, ground_y=0.0)


def arch_5() -> Structure:
    """5-block arch: 2 abutments + 3 voussoirs (middle one is keystone).

    Feasible: place abutments first, then side voussoirs, then keystone.
    """
    return _parametric_arch(n_voussoirs=3, span=4.0, rise=2.0, thickness=0.8)


def arch_7() -> Structure:
    """7-block arch: 2 abutments + 5 voussoirs. More challenging — needs
    correct ordering to maintain stability during construction.
    """
    return _parametric_arch(n_voussoirs=5, span=4.0, rise=2.0, thickness=0.7)


def unstable_tower() -> Structure:
    """Intentionally infeasible: a top-heavy inverted pyramid.

    Three blocks stacked with decreasing base width — the top block
    overhangs so much that no assembly order is stable without modification.

         ___________
        |     2     |   <- wide top (overhangs)
         _____|_____
          |   1   |     <- medium middle
           ___|___
            | 0 |       <- narrow base
            =====
    """
    blocks = [
        # Block 0: narrow base
        Block(id=0, vertices=np.array([
            [-0.5, 0.0], [0.5, 0.0], [0.5, 1.0], [-0.5, 1.0],
        ]), mass=1.0),
        # Block 1: medium middle
        Block(id=1, vertices=np.array([
            [-1.0, 1.0], [1.0, 1.0], [1.0, 2.0], [-1.0, 2.0],
        ]), mass=1.5),
        # Block 2: wide top (overhanging)
        Block(id=2, vertices=np.array([
            [-2.0, 2.0], [2.0, 2.0], [2.0, 3.0], [-2.0, 3.0],
        ]), mass=2.0),
    ]
    return Structure(blocks=blocks, ground_y=0.0)


def pyramid_6() -> Structure:
    """6-block pyramid — FEASIBLE with bottom-up ordering.

    A stable structure where CEGIS should find a valid sequence quickly.
    Three base blocks, two middle, one top.

       5
      3 4
     0 1 2
    ========
    """
    w = 1.5  # block width
    h = 1.0  # block height
    blocks = [
        # Bottom row
        Block(id=0, vertices=np.array([
            [-2.25, 0], [-0.75, 0], [-0.75, h], [-2.25, h],
        ]), mass=1.5),
        Block(id=1, vertices=np.array([
            [-0.75, 0], [0.75, 0], [0.75, h], [-0.75, h],
        ]), mass=1.5),
        Block(id=2, vertices=np.array([
            [0.75, 0], [2.25, 0], [2.25, h], [0.75, h],
        ]), mass=1.5),
        # Middle row (offset by half-block)
        Block(id=3, vertices=np.array([
            [-1.5, h], [0.0, h], [0.0, 2*h], [-1.5, 2*h],
        ]), mass=1.2),
        Block(id=4, vertices=np.array([
            [0.0, h], [1.5, h], [1.5, 2*h], [0.0, 2*h],
        ]), mass=1.2),
        # Top
        Block(id=5, vertices=np.array([
            [-0.75, 2*h], [0.75, 2*h], [0.75, 3*h], [-0.75, 3*h],
        ]), mass=1.0),
    ]
    return Structure(blocks=blocks, ground_y=0.0)


def wall_4() -> Structure:
    """Simple 4-block wall — trivially feasible bottom-up.

    Two rows of two blocks each. Good for basic CEGIS demonstration.

     2 3
     0 1
    =====
    """
    w, h = 1.5, 1.0
    blocks = [
        Block(id=0, vertices=np.array([[-w, 0], [0, 0], [0, h], [-w, h]]), mass=1.0),
        Block(id=1, vertices=np.array([[0, 0], [w, 0], [w, h], [0, h]]), mass=1.0),
        Block(id=2, vertices=np.array([[-w, h], [0, h], [0, 2*h], [-w, 2*h]]), mass=1.0),
        Block(id=3, vertices=np.array([[0, h], [w, h], [w, 2*h], [0, 2*h]]), mass=1.0),
    ]
    return Structure(blocks=blocks, ground_y=0.0)


def cantilever_5() -> Structure:
    """5-block cantilever — progressively overhanging blocks.

    Each block extends further to the right. Infeasible without counterweights
    or geometry repair for extreme overhangs.

    Block 4 overhangs significantly to trigger repair synthesis.
    """
    blocks = [
        Block(id=0, vertices=np.array([
            [-1.0, 0.0], [1.0, 0.0], [1.0, 0.6], [-1.0, 0.6],
        ]), mass=2.0),
        Block(id=1, vertices=np.array([
            [-0.5, 0.6], [1.5, 0.6], [1.5, 1.2], [-0.5, 1.2],
        ]), mass=1.5),
        Block(id=2, vertices=np.array([
            [0.0, 1.2], [2.0, 1.2], [2.0, 1.8], [0.0, 1.8],
        ]), mass=1.2),
        Block(id=3, vertices=np.array([
            [0.5, 1.8], [2.5, 1.8], [2.5, 2.4], [0.5, 2.4],
        ]), mass=1.0),
        Block(id=4, vertices=np.array([
            [1.0, 2.4], [3.5, 2.4], [3.5, 3.0], [1.0, 3.0],
        ]), mass=1.0),
    ]
    return Structure(blocks=blocks, ground_y=0.0)
