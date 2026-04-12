"""CEGIS loop for assembly sequence planning.

Counterexample-Guided Inductive Synthesis applied to assembly:
  1. Propose a topological ordering of blocks consistent with known precedence constraints
  2. Verify each placement step via an extensible verifier chain (stability, kinematic, ...)
  3. On any verifier failure, extract precedence constraints and retry
  4. Repeat until success or exhaustion (constraint cycle → INFEASIBLE)

The verifier chain is the extension point: each verifier contributes its own
class of precedence constraints (stability: support, kinematic: drop-path
clearance, ...). CEGIS itself is agnostic to the semantics of the checks.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .geometry import Structure
from .verifiers import Verifier, VerifierResult, default_chain
from .verifiers.base import PrecedenceConstraint


@dataclass
class StepRecord:
    """One placement step within a CEGIS round."""
    step: int
    block: int
    verifier_results: list[VerifierResult] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return all(vr.feasible for vr in self.verifier_results)

    @property
    def failed_verifier(self) -> str | None:
        for vr in self.verifier_results:
            if not vr.feasible:
                return vr.verifier
        return None


@dataclass
class CEGISRound:
    """Record of one CEGIS iteration."""
    round_num: int
    candidate: list[int]
    failure_step: int | None
    failed_block: int | None
    failed_verifier: str | None
    new_constraints: list[PrecedenceConstraint]
    steps: list[StepRecord]
    pruned_count: int = 0


@dataclass
class CEGISResult:
    """Final result of the CEGIS loop."""
    feasible: bool
    sequence: list[int] | None
    rounds: list[CEGISRound]
    constraints: list[PrecedenceConstraint]
    total_pruned: int = 0


def solve(
    structure: Structure,
    max_rounds: int = 200,
    seed: int | None = None,
    friction: float = 0.7,
    verifiers: list[Verifier] | None = None,
) -> CEGISResult:
    """Run the CEGIS loop to find a valid assembly sequence.

    Verifiers default to default_chain() — currently [Kinematic, Stability, Landing]
    in cheapest-first order. Pass a custom chain to ablate (e.g., stability-only)
    or extend (e.g., add robot reach).
    """
    rng = random.Random(seed)
    block_ids = [b.id for b in structure.blocks]
    n = len(block_ids)

    if verifiers is None:
        verifiers = default_chain(friction=friction)

    constraints: set[PrecedenceConstraint] = set()
    rounds: list[CEGISRound] = []
    total_pruned = 0

    for round_num in range(max_rounds):
        candidate = _sample_topological_sort(block_ids, constraints, rng)
        if candidate is None:
            return CEGISResult(
                feasible=False,
                sequence=None,
                rounds=rounds,
                constraints=list(constraints),
                total_pruned=total_pruned,
            )

        failure_step = None
        failed_block = None
        failed_verifier = None
        new_constraints: list[PrecedenceConstraint] = []
        step_records: list[StepRecord] = []

        for k in range(n):
            step_rec = StepRecord(step=k, block=candidate[k])

            for verifier in verifiers:
                vr = verifier.check(structure, candidate, k, block_ids)
                step_rec.verifier_results.append(vr)
                if not vr.feasible:
                    break

            step_records.append(step_rec)

            if not step_rec.feasible:
                failure_step = k
                failed_block = candidate[k]
                failed_verifier = step_rec.failed_verifier
                for vr in step_rec.verifier_results:
                    if not vr.feasible:
                        for pc in vr.new_constraints:
                            new_constraints.append(pc)
                            constraints.add(pc)

                total_pruned += _estimate_pruned(n, len(new_constraints))
                break

        rounds.append(CEGISRound(
            round_num=round_num,
            candidate=candidate,
            failure_step=failure_step,
            failed_block=failed_block,
            failed_verifier=failed_verifier,
            new_constraints=new_constraints,
            steps=step_records,
            pruned_count=_estimate_pruned(n, len(new_constraints)),
        ))

        if failure_step is None:
            return CEGISResult(
                feasible=True,
                sequence=candidate,
                rounds=rounds,
                constraints=list(constraints),
                total_pruned=total_pruned,
            )

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
    """Kahn's algorithm with random tie-breaking. Returns None on cycle."""
    in_degree = {b: 0 for b in block_ids}
    successors: dict[int, list[int]] = {b: [] for b in block_ids}

    for pc in constraints:
        if pc.before in in_degree and pc.after in in_degree:
            successors[pc.before].append(pc.after)
            in_degree[pc.after] += 1

    queue = [b for b in block_ids if in_degree[b] == 0]
    result = []

    while queue:
        idx = rng.randrange(len(queue))
        node = queue.pop(idx)
        result.append(node)
        for succ in successors[node]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    if len(result) != len(block_ids):
        return None

    return result


def _estimate_pruned(n: int, new_constraints: int) -> int:
    import math
    if n <= 1 or new_constraints <= 0:
        return 0
    total = math.factorial(n)
    return min(total, new_constraints * total // 2)
