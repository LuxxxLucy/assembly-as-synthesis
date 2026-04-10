"""CEGIS loop for assembly sequence planning.

Counterexample-Guided Inductive Synthesis applied to assembly:
  1. Propose a topological ordering of blocks consistent with known precedence constraints
  2. Verify stability at each step via LP
  3. On failure, extract precedence constraints (which blocks must come first)
  4. Repeat until success or exhaustion (all orderings pruned)

When exhausted, returns INFEASIBLE — the signal for repair synthesis.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .geometry import Structure
from .stability import check_stability_at_step, find_minimal_support_set, StabilityResult


@dataclass
class PrecedenceConstraint:
    """Block `before` must be placed before block `after`."""
    before: int
    after: int
    reason: str = ""

    def __hash__(self):
        return hash((self.before, self.after))

    def __eq__(self, other):
        return self.before == other.before and self.after == other.after


@dataclass
class CEGISRound:
    """Record of one CEGIS iteration."""
    round_num: int
    candidate: list[int]  # proposed sequence
    failure_step: int | None  # step where instability detected (None = success)
    failed_block: int | None
    new_constraints: list[PrecedenceConstraint]
    stability_results: list[StabilityResult]  # per-step results up to failure
    pruned_count: int = 0  # estimated permutations eliminated


@dataclass
class CEGISResult:
    """Final result of the CEGIS loop."""
    feasible: bool
    sequence: list[int] | None  # valid assembly order (if feasible)
    rounds: list[CEGISRound]  # full trace of all attempts
    constraints: list[PrecedenceConstraint]
    total_pruned: int = 0  # total permutations eliminated


def solve(
    structure: Structure,
    max_rounds: int = 200,
    seed: int | None = None,
    friction: float = 0.7,
) -> CEGISResult:
    """Run the CEGIS loop to find a valid assembly sequence.

    Returns CEGISResult with either a feasible sequence or INFEASIBLE + trace.
    """
    rng = random.Random(seed)
    block_ids = [b.id for b in structure.blocks]
    n = len(block_ids)

    constraints: set[PrecedenceConstraint] = set()
    rounds: list[CEGISRound] = []
    total_pruned = 0

    for round_num in range(max_rounds):
        # Generate a candidate: topological sort consistent with constraints
        candidate = _sample_topological_sort(block_ids, constraints, rng)
        if candidate is None:
            # No valid ordering exists — INFEASIBLE
            return CEGISResult(
                feasible=False,
                sequence=None,
                rounds=rounds,
                constraints=list(constraints),
                total_pruned=total_pruned,
            )

        # Verify stability at each step
        failure_step = None
        failed_block = None
        new_constraints: list[PrecedenceConstraint] = []
        step_results: list[StabilityResult] = []

        for k in range(n):
            result = check_stability_at_step(structure, candidate, k, friction)
            step_results.append(result)

            if not result.feasible:
                failure_step = k
                failed_block = candidate[k]

                # Counterexample generalization: find which blocks must precede
                placed_before = candidate[:k]
                support_set = find_minimal_support_set(
                    structure, failed_block, placed_before, friction
                )

                # For each needed support not yet placed, add precedence constraint
                placed_set = set(placed_before)
                all_block_ids = set(block_ids)
                # Find blocks that contact failed_block but aren't placed
                contacts = structure.detect_contacts(block_ids)
                neighbors = set()
                for c in contacts:
                    if c.block_a == failed_block and c.block_b >= 0:
                        neighbors.add(c.block_b)
                    elif c.block_b == failed_block and c.block_a >= 0:
                        neighbors.add(c.block_a)

                # The support set tells us which neighbors are necessary
                for sb in support_set:
                    pc = PrecedenceConstraint(
                        before=sb, after=failed_block,
                        reason=f"Round {round_num}: block {sb} must support block {failed_block}"
                    )
                    new_constraints.append(pc)
                    constraints.add(pc)

                # If no specific support found, require ALL neighbors below
                if not support_set and neighbors:
                    for nb in neighbors:
                        if nb not in placed_set:
                            pc = PrecedenceConstraint(
                                before=nb, after=failed_block,
                                reason=f"Round {round_num}: block {nb} neighbors block {failed_block}"
                            )
                            new_constraints.append(pc)
                            constraints.add(pc)

                # Estimate pruned permutations (conservative: n!/2 per constraint)
                pruned = _estimate_pruned(n, len(new_constraints))
                total_pruned += pruned

                break

        round_record = CEGISRound(
            round_num=round_num,
            candidate=candidate,
            failure_step=failure_step,
            failed_block=failed_block,
            new_constraints=new_constraints,
            stability_results=step_results,
            pruned_count=_estimate_pruned(n, len(new_constraints)),
        )
        rounds.append(round_record)

        if failure_step is None:
            # Success!
            return CEGISResult(
                feasible=True,
                sequence=candidate,
                rounds=rounds,
                constraints=list(constraints),
                total_pruned=total_pruned,
            )

    # Max rounds exceeded
    return CEGISResult(
        feasible=False,
        sequence=None,
        rounds=rounds,
        constraints=list(constraints),
        total_pruned=total_pruned,
    )


def _sample_topological_sort(
    block_ids: list[int],
    constraints: set[PrecedenceConstraint],
    rng: random.Random,
) -> list[int] | None:
    """Sample a random topological ordering consistent with precedence constraints.

    Uses Kahn's algorithm with random tie-breaking.
    Returns None if the constraint graph has a cycle (infeasible).
    """
    # Build adjacency and in-degree
    in_degree = {b: 0 for b in block_ids}
    successors: dict[int, list[int]] = {b: [] for b in block_ids}

    for pc in constraints:
        if pc.before in in_degree and pc.after in in_degree:
            successors[pc.before].append(pc.after)
            in_degree[pc.after] += 1

    # Kahn's algorithm with random selection
    queue = [b for b in block_ids if in_degree[b] == 0]
    result = []

    while queue:
        # Random tie-breaking for exploration
        idx = rng.randrange(len(queue))
        node = queue.pop(idx)
        result.append(node)

        for succ in successors[node]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    if len(result) != len(block_ids):
        return None  # Cycle — infeasible

    return result


def _estimate_pruned(n: int, new_constraints: int) -> int:
    """Rough estimate of permutations eliminated by new constraints."""
    import math
    if n <= 1 or new_constraints <= 0:
        return 0
    # Each a ≺ b constraint eliminates roughly n!/2 orderings
    total = math.factorial(n)
    return min(total, new_constraints * total // 2)
