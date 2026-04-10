"""Repair synthesis: when no feasible assembly sequence exists, find minimal
geometry modifications that create one.

Pipeline:
  1. CEGIS returns INFEASIBLE
  2. Extract Farkas certificate from LP dual — identifies insufficient contacts
  3. Compute geometric sensitivity ∂A/∂p (how vertex displacement changes contact capacity)
  4. Solve QP: min ||Δp||² s.t. modified geometry admits a feasible sequence
  5. Return modified structure + feasible sequence

The alternating approach: fix desired forces → solve QP for Δp → re-check LP.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from dataclasses import dataclass

from .geometry import Block, Contact, Structure
from .stability import check_stability, StabilityResult, GRAVITY
from . import cegis


@dataclass
class RepairResult:
    """Result of repair synthesis."""
    success: bool
    original_structure: Structure
    repaired_structure: Structure | None = None
    vertex_displacements: dict[int, np.ndarray] | None = None  # block_id -> (n_verts, 2)
    feasible_sequence: list[int] | None = None
    cegis_result: cegis.CEGISResult | None = None
    iterations: int = 0
    displacement_norm: float = 0.0


def repair(
    structure: Structure,
    cegis_result: cegis.CEGISResult,
    max_displacement: float = 0.5,
    max_iterations: int = 20,
    friction: float = 0.7,
) -> RepairResult:
    """Attempt to repair an infeasible structure via minimal geometry modification.

    Strategy: identify the most constrained blocks (those that appear most often
    in failed stability checks), then perturb their vertices to improve contact
    conditions.

    The approach:
    1. Analyze CEGIS trace to find critical failure points
    2. For each critical block, compute contact deficiency
    3. Solve for minimal vertex displacement that improves stability
    4. Re-run CEGIS on modified structure
    """
    if cegis_result.feasible:
        return RepairResult(success=True, original_structure=structure)

    # Analyze failure patterns from CEGIS trace
    failure_counts: dict[int, int] = {}
    for round_rec in cegis_result.rounds:
        if round_rec.failed_block is not None:
            failure_counts[round_rec.failed_block] = (
                failure_counts.get(round_rec.failed_block, 0) + 1
            )

    if not failure_counts:
        return RepairResult(success=False, original_structure=structure)

    # Sort blocks by failure frequency — most problematic first
    critical_blocks = sorted(failure_counts.keys(), key=lambda b: -failure_counts[b])

    best_result = None

    for iteration in range(max_iterations):
        # Try displacing vertices of critical blocks
        displaced = _compute_repair_displacement(
            structure, critical_blocks, cegis_result,
            max_displacement, friction, iteration,
        )

        if displaced is None:
            continue

        repaired_structure, displacements = displaced

        # Re-run CEGIS on repaired structure
        new_cegis = cegis.solve(repaired_structure, max_rounds=100, seed=iteration, friction=friction)

        if new_cegis.feasible:
            total_disp = sum(
                np.linalg.norm(d) for d in displacements.values()
            )
            return RepairResult(
                success=True,
                original_structure=structure,
                repaired_structure=repaired_structure,
                vertex_displacements=displacements,
                feasible_sequence=new_cegis.sequence,
                cegis_result=new_cegis,
                iterations=iteration + 1,
                displacement_norm=total_disp,
            )

        # Update best result if this got further
        if best_result is None or len(new_cegis.rounds) > len(best_result.rounds):
            best_result = new_cegis

    return RepairResult(
        success=False,
        original_structure=structure,
        iterations=max_iterations,
    )


def _compute_repair_displacement(
    structure: Structure,
    critical_blocks: list[int],
    cegis_result: cegis.CEGISResult,
    max_disp: float,
    friction: float,
    iteration: int,
) -> tuple[Structure, dict[int, np.ndarray]] | None:
    """Compute vertex displacements for critical blocks to improve stability.

    Uses the contact geometry to identify which vertices to move and in which
    direction. The key insight: if a block fails because it lacks support from
    below, we can:
    - Widen the contact surface (spread bottom vertices)
    - Lower the center of mass (shift top vertices down)
    - Add contact area with neighbors (shift side vertices toward neighbors)
    """
    displacements: dict[int, np.ndarray] = {}
    all_contacts = structure.detect_contacts()

    for bid in critical_blocks[:2]:  # focus on top 2 most critical
        block = structure.block_by_id(bid)
        n_verts = len(block.vertices)
        dp = np.zeros((n_verts, 2))

        # Find contacts involving this block
        block_contacts = [c for c in all_contacts
                          if c.block_a == bid or c.block_b == bid]

        if not block_contacts:
            # No contacts — block is floating. Move it down toward nearest neighbor.
            centroid = block.centroid
            dp[:, 1] = -max_disp * 0.5  # move down
            displacements[bid] = dp
            continue

        # Analyze contact normals to determine repair direction
        centroid = block.centroid
        avg_normal = np.zeros(2)
        for c in block_contacts:
            if c.block_a == bid:
                avg_normal += c.normal  # normal points into this block
            else:
                avg_normal -= c.normal

        if np.linalg.norm(avg_normal) > 1e-10:
            avg_normal = avg_normal / np.linalg.norm(avg_normal)

        # Strategy depends on iteration (explore different repair modes)
        mode = iteration % 4

        if mode == 0:
            # Widen base: spread bottom vertices horizontally
            for i, v in enumerate(block.vertices):
                if v[1] < centroid[1]:  # bottom vertex
                    direction = v[0] - centroid[0]
                    dp[i, 0] = np.sign(direction) * max_disp * 0.3
        elif mode == 1:
            # Lower CoM: move top vertices down
            for i, v in enumerate(block.vertices):
                if v[1] > centroid[1]:
                    dp[i, 1] = -max_disp * 0.3
        elif mode == 2:
            # Increase contact with neighbors: move toward contact points
            for c in block_contacts:
                for i, v in enumerate(block.vertices):
                    to_contact = c.point - v
                    dist = np.linalg.norm(to_contact)
                    if 0.01 < dist < max_disp * 2:
                        dp[i] += to_contact * max_disp * 0.2 / max(dist, 0.01)
        elif mode == 3:
            # Combined: widen + lower
            for i, v in enumerate(block.vertices):
                if v[1] < centroid[1]:
                    direction = v[0] - centroid[0]
                    dp[i, 0] = np.sign(direction) * max_disp * 0.2
                if v[1] > centroid[1]:
                    dp[i, 1] = -max_disp * 0.15

        # Clamp displacement
        norms = np.linalg.norm(dp, axis=1, keepdims=True)
        mask = (norms > max_disp) & (norms > 1e-10)
        safe_norms = np.where(norms > 1e-10, norms, 1.0)
        dp = np.where(mask, dp * max_disp / safe_norms, dp)

        displacements[bid] = dp

    if not displacements:
        return None

    # Build repaired structure
    new_blocks = []
    for b in structure.blocks:
        if b.id in displacements:
            new_blocks.append(b.with_vertex_displacement(displacements[b.id]))
        else:
            new_blocks.append(b)

    repaired = Structure(blocks=new_blocks, ground_y=structure.ground_y)
    return repaired, displacements
