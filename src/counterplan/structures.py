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


def pyramid_10() -> Structure:
    """10-block pyramid (4-3-2-1) — FEASIBLE bottom-up.

    3,628,800 possible orderings but CEGIS solves in ~5 rounds.
    Demonstrates efficiency on large search spaces.

         9
        7 8
       4 5 6
      0 1 2 3
    ============
    """
    w, h = 1.5, 1.0
    blocks = []
    bid = 0
    rows = [4, 3, 2, 1]
    for row_i, n in enumerate(rows):
        y = row_i * h
        row_width = n * w
        x_start = -row_width / 2
        for col in range(n):
            x0 = x_start + col * w
            blocks.append(Block(id=bid, vertices=np.array([
                [x0, y], [x0 + w, y], [x0 + w, y + h], [x0, y + h],
            ]), mass=1.5 if row_i == 0 else 1.0))
            bid += 1
    return Structure(blocks=blocks, ground_y=0.0)


def gothic_arch_9() -> Structure:
    """9-block pointed (Gothic) arch — likely INFEASIBLE without scaffolding.

    2 thick abutments + 6 voussoirs + 1 keystone along two circular arcs
    meeting at a pointed peak. High horizontal thrust from pointed geometry.

          *
         / \\
        /   \\
       /     \\
      |       |
      |       |
      |_______|
    """
    span = 5.0
    peak_h = 4.0
    abut_h = 2.0
    thick = 0.6

    # Arc geometry: each arc centered at opposite springing
    cx_l = -span / 2  # left springing = center for right-side arc
    cx_r = span / 2   # right springing = center for left-side arc
    cy = abut_h

    # Radius from springing to peak: R such that arc passes through peak
    R = (span**2 / 4 + peak_h**2) / (2 * span / 2)

    blocks = []

    # Abutments (thick for thrust resistance)
    abut_w = 1.2
    # Right abutment (id=0)
    blocks.append(Block(id=0, vertices=np.array([
        [span / 2 - 0.1, 0.0], [span / 2 + abut_w, 0.0],
        [span / 2 + abut_w, abut_h], [span / 2 - 0.1, abut_h],
    ]), mass=3.0))
    # Left abutment (id=1)
    blocks.append(Block(id=1, vertices=np.array([
        [-span / 2 - abut_w, 0.0], [-span / 2 + 0.1, 0.0],
        [-span / 2 + 0.1, abut_h], [-span / 2 - abut_w, abut_h],
    ]), mass=3.0))

    # Right-side voussoirs (id=2,3,4): arc centered at LEFT springing
    a_start_r = np.arctan2(0, span)
    a_end_r = np.arctan2(peak_h, span / 2)
    r_angles = np.linspace(a_start_r, a_end_r, 4)

    for i in range(3):
        a0, a1 = r_angles[i], r_angles[i + 1]
        ir = np.array([cx_l + R * np.cos(a0), cy + R * np.sin(a0)])
        or_ = np.array([cx_l + (R + thick) * np.cos(a0), cy + (R + thick) * np.sin(a0)])
        ol = np.array([cx_l + (R + thick) * np.cos(a1), cy + (R + thick) * np.sin(a1)])
        il = np.array([cx_l + R * np.cos(a1), cy + R * np.sin(a1)])
        blocks.append(Block(id=i + 2, vertices=np.array([ir, or_, ol, il]), mass=1.0))

    # Left-side voussoirs (id=5,6,7): arc centered at RIGHT springing
    a_start_l = np.pi - a_start_r
    a_end_l = np.pi - a_end_r
    l_angles = np.linspace(a_start_l, a_end_l, 4)

    for i in range(3):
        a0, a1 = l_angles[i], l_angles[i + 1]
        ir = np.array([cx_r + R * np.cos(a0), cy + R * np.sin(a0)])
        or_ = np.array([cx_r + (R + thick) * np.cos(a0), cy + (R + thick) * np.sin(a0)])
        ol = np.array([cx_r + (R + thick) * np.cos(a1), cy + (R + thick) * np.sin(a1)])
        il = np.array([cx_r + R * np.cos(a1), cy + R * np.sin(a1)])
        blocks.append(Block(id=i + 5, vertices=np.array([ir, or_, ol, il]), mass=1.0))

    # Keystone (id=8): wedge at the peak
    ra = r_angles[-1]
    la = l_angles[-1]
    blocks.append(Block(id=8, vertices=np.array([
        [cx_l + R * np.cos(ra), cy + R * np.sin(ra)],
        [cx_l + (R + thick) * np.cos(ra), cy + (R + thick) * np.sin(ra)],
        [cx_r + (R + thick) * np.cos(la), cy + (R + thick) * np.sin(la)],
        [cx_r + R * np.cos(la), cy + R * np.sin(la)],
    ]), mass=0.8))

    return Structure(blocks=blocks, ground_y=0.0)


def post_and_lintel_5() -> Structure:
    """5-block post-and-lintel (Stonehenge-like) — FEASIBLE.

    2 columns (2 blocks each) + 1 lintel spanning the gap.
    CEGIS learns lintel-last constraint quickly (~2 rounds).

     _______________
    |       4       |
     ___         ___
    | 3 |       | 1 |
    |___|       |___|
    | 2 |       | 0 |
    |___|       |___|
    =================
    """
    col_w, col_h = 1.0, 1.2
    gap = 2.5
    lintel_overhang = 0.3

    # Right column
    rx = gap / 2
    blocks = [
        Block(id=0, vertices=np.array([
            [rx, 0.0], [rx + col_w, 0.0],
            [rx + col_w, col_h], [rx, col_h],
        ]), mass=1.5),
        Block(id=1, vertices=np.array([
            [rx, col_h], [rx + col_w, col_h],
            [rx + col_w, 2 * col_h], [rx, 2 * col_h],
        ]), mass=1.5),
    ]

    # Left column
    lx = -gap / 2 - col_w
    blocks += [
        Block(id=2, vertices=np.array([
            [lx, 0.0], [lx + col_w, 0.0],
            [lx + col_w, col_h], [lx, col_h],
        ]), mass=1.5),
        Block(id=3, vertices=np.array([
            [lx, col_h], [lx + col_w, col_h],
            [lx + col_w, 2 * col_h], [lx, 2 * col_h],
        ]), mass=1.5),
    ]

    # Lintel
    lintel_l = lx - lintel_overhang
    lintel_r = rx + col_w + lintel_overhang
    blocks.append(Block(id=4, vertices=np.array([
        [lintel_l, 2 * col_h], [lintel_r, 2 * col_h],
        [lintel_r, 2 * col_h + 0.6], [lintel_l, 2 * col_h + 0.6],
    ]), mass=2.5))

    return Structure(blocks=blocks, ground_y=0.0)
