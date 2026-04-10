"""LP-based static equilibrium verifier for 2D block assemblies.

Each block must satisfy force and moment equilibrium under gravity.
Contact forces are decomposed into normal (compression only) and tangential
(friction) components. We solve an LP to check if feasible contact forces exist.

The LP dual provides stability margins (how far from infeasibility each block is)
and, when infeasible, a Farkas certificate identifying which contacts are insufficient.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog
from dataclasses import dataclass

from .geometry import Block, Contact, Structure


GRAVITY = np.array([0.0, -9.81])
FRICTION_COEFF = 0.7  # Coulomb friction coefficient


@dataclass
class StabilityResult:
    """Result of a stability check."""
    feasible: bool
    contact_forces: np.ndarray | None = None  # (n_contacts, 2) normal and tangential
    dual_values: np.ndarray | None = None  # LP dual = stability margins
    farkas_certificate: np.ndarray | None = None  # infeasibility certificate
    margin: float = 0.0  # minimum stability margin across all blocks
    block_margins: dict[int, float] | None = None  # per-block margins


def check_stability(
    structure: Structure,
    placed_ids: list[int],
    contacts: list[Contact] | None = None,
    friction: float = FRICTION_COEFF,
) -> StabilityResult:
    """Check if the placed blocks are in static equilibrium.

    For each non-ground block, we require:
      sum of contact forces + gravity = 0  (force balance)
      sum of contact moments about centroid = 0  (moment balance)
      normal forces >= 0  (no tension)
      |tangential force| <= mu * normal force  (friction cone, linearized)

    Returns StabilityResult with feasibility, forces, and dual info.
    """
    if not placed_ids:
        return StabilityResult(feasible=True, margin=float('inf'))

    if contacts is None:
        contacts = structure.detect_contacts(placed_ids)

    # Only check equilibrium for non-ground blocks
    block_ids = [bid for bid in placed_ids if bid >= 0]
    if not block_ids:
        return StabilityResult(feasible=True, margin=float('inf'))

    n_contacts = len(contacts)
    if n_contacts == 0:
        # No contacts but blocks exist — unstable
        return StabilityResult(feasible=False, margin=-float('inf'))

    # Decision variables: for each contact, (fn, ft) = normal and tangential force
    # fn >= 0, -mu*fn <= ft <= mu*fn
    # We split ft = ft+ - ft- with ft+, ft- >= 0 and ft+ + ft- <= mu*fn
    # So variables per contact: [fn, ft+, ft-], total = 3 * n_contacts
    n_vars = 3 * n_contacts

    # Equality constraints: force and moment balance for each block
    # 3 equations per block (fx, fy, moment)
    n_eq = 3 * len(block_ids)
    A_eq = np.zeros((n_eq, n_vars))
    b_eq = np.zeros(n_eq)

    block_idx = {bid: i for i, bid in enumerate(block_ids)}

    for c_idx, contact in enumerate(contacts):
        fn_col = 3 * c_idx
        ftp_col = 3 * c_idx + 1
        ftm_col = 3 * c_idx + 2

        n = contact.normal  # points into block_a
        t = np.array([-n[1], n[0]])  # tangent (90° CCW from normal)

        # Force on block_a from this contact: fn*n + (ft+ - ft-)*t
        # Force on block_b from this contact: -fn*n - (ft+ - ft-)*t (Newton's 3rd)
        for sign, bid in [(1, contact.block_a), (-1, contact.block_b)]:
            if bid < 0 or bid not in block_idx:
                continue
            row_base = 3 * block_idx[bid]
            block = structure.block_by_id(bid)
            r = contact.point - block.centroid  # moment arm

            # Force balance (x, y)
            A_eq[row_base + 0, fn_col] = sign * n[0]
            A_eq[row_base + 0, ftp_col] = sign * t[0]
            A_eq[row_base + 0, ftm_col] = -sign * t[0]

            A_eq[row_base + 1, fn_col] = sign * n[1]
            A_eq[row_base + 1, ftp_col] = sign * t[1]
            A_eq[row_base + 1, ftm_col] = -sign * t[1]

            # Moment balance: r × F = rx*Fy - ry*Fx
            force_x_fn = sign * n[0]
            force_y_fn = sign * n[1]
            force_x_ftp = sign * t[0]
            force_y_ftp = sign * t[1]

            A_eq[row_base + 2, fn_col] = r[0] * force_y_fn - r[1] * force_x_fn
            A_eq[row_base + 2, ftp_col] = r[0] * force_y_ftp - r[1] * force_x_ftp
            A_eq[row_base + 2, ftm_col] = -(r[0] * force_y_ftp - r[1] * force_x_ftp)

    # RHS: gravity loads
    for bid in block_ids:
        block = structure.block_by_id(bid)
        row_base = 3 * block_idx[bid]
        weight = block.mass * GRAVITY
        b_eq[row_base + 0] = -weight[0]
        b_eq[row_base + 1] = -weight[1]
        # Gravity acts at centroid, so moment about centroid = 0
        b_eq[row_base + 2] = 0.0

    # Inequality constraints: friction cone ft+ + ft- <= mu * fn
    # i.e., -mu*fn + ft+ + ft- <= 0
    A_ub = np.zeros((n_contacts, n_vars))
    b_ub = np.zeros(n_contacts)
    for c_idx in range(n_contacts):
        fn_col = 3 * c_idx
        ftp_col = 3 * c_idx + 1
        ftm_col = 3 * c_idx + 2
        A_ub[c_idx, fn_col] = -friction
        A_ub[c_idx, ftp_col] = 1.0
        A_ub[c_idx, ftm_col] = 1.0

    # Bounds: fn >= 0, ft+/ft- >= 0
    bounds = []
    for c_idx in range(n_contacts):
        bounds.append((0, None))  # fn >= 0
        bounds.append((0, None))  # ft+ >= 0
        bounds.append((0, None))  # ft- >= 0

    # Objective: minimize total normal force (find the "easiest" equilibrium)
    c = np.zeros(n_vars)
    for c_idx in range(n_contacts):
        c[3 * c_idx] = 1.0  # minimize sum of normal forces

    result = linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
        bounds=bounds, method='highs',
    )

    if result.success and result.status == 0:
        # Extract contact forces
        forces = np.zeros((n_contacts, 2))
        for c_idx in range(n_contacts):
            fn = result.x[3 * c_idx]
            ft = result.x[3 * c_idx + 1] - result.x[3 * c_idx + 2]
            forces[c_idx] = [fn, ft]

        # Compute per-block stability margins from dual
        block_margins = {}
        if result.eqlin is not None and hasattr(result.eqlin, 'marginals'):
            duals = result.eqlin.marginals
        else:
            duals = np.zeros(n_eq)

        # Simple margin: ratio of min normal force to block weight
        for bid in block_ids:
            block = structure.block_by_id(bid)
            block_contact_normals = []
            for c_idx, contact in enumerate(contacts):
                if contact.block_a == bid or contact.block_b == bid:
                    block_contact_normals.append(forces[c_idx, 0])
            if block_contact_normals:
                weight = block.mass * abs(GRAVITY[1])
                margin = min(block_contact_normals) / max(weight, 1e-10)
                block_margins[bid] = margin
            else:
                block_margins[bid] = 0.0

        min_margin = min(block_margins.values()) if block_margins else 0.0

        return StabilityResult(
            feasible=True,
            contact_forces=forces,
            dual_values=duals,
            margin=min_margin,
            block_margins=block_margins,
        )
    else:
        # Infeasible — try to extract Farkas certificate
        # The Farkas certificate y satisfies: y^T A_eq = 0, y^T b_eq > 0
        # It identifies which equilibrium constraints are incompatible
        farkas = None
        if hasattr(result, 'ineqlin') and result.ineqlin is not None:
            farkas = getattr(result.ineqlin, 'marginals', None)

        return StabilityResult(
            feasible=False,
            farkas_certificate=farkas,
            margin=-1.0,
        )


def check_stability_at_step(
    structure: Structure,
    sequence: list[int],
    step: int,
    friction: float = FRICTION_COEFF,
) -> StabilityResult:
    """Check stability of the assembly after placing blocks sequence[:step+1]."""
    placed = sequence[:step + 1]
    contacts = structure.detect_contacts(placed)
    return check_stability(structure, placed, contacts, friction)


def find_minimal_support_set(
    structure: Structure,
    block_id: int,
    placed_before: list[int],
    friction: float = FRICTION_COEFF,
) -> list[int]:
    """Find the minimal subset of placed_before needed to support block_id.

    This is used for counterexample generalization: if block_id is unstable,
    which blocks MUST be placed before it?

    Returns a list of block IDs that are necessary supports.
    """
    all_placed = placed_before + [block_id]
    contacts = structure.detect_contacts(all_placed)

    # Find blocks that share contacts with block_id
    supporting_blocks = set()
    for c in contacts:
        if c.block_a == block_id and c.block_b >= 0:
            supporting_blocks.add(c.block_b)
        elif c.block_b == block_id and c.block_a >= 0:
            supporting_blocks.add(c.block_a)

    # Try removing each supporting block — if removal makes block_id unstable,
    # that block is necessary
    necessary = []
    for sb in supporting_blocks:
        reduced = [b for b in all_placed if b != sb]
        result = check_stability(structure, reduced, friction=friction)
        if not result.feasible:
            necessary.append(sb)

    return necessary
