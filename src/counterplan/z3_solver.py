"""Z3-based CEGIS proposer.

The output we care about is an **assembly plan**: a sequence of actions
  plan = [ place(b_0), place(b_1), ..., place(b_{n-1}) ].

So we encode one SMT variable per step, not per block:

    action[k] ∈ block_ids          for k = 0 .. n-1
    Distinct(action[0], ..., action[n-1])         # each block placed exactly once.

A learned precedence "A must precede B" becomes the clause

    ∀ k.  action[k] == B  ⟹  ∃ k' < k.  action[k'] == A

which in SMT unfolds to

    And([ Implies(action[k] == B, Or([action[k'] == A for k' in range(k)]))
          for k in range(n) ]).

The CEGIS loop is otherwise identical to counterplan.cegis: Z3 proposes a
plan; the same verifier chain runs; on the first failing step we harvest
its precedence constraints, add the corresponding clauses, re-solve.
`unsat` means the constraint graph has a cycle — INFEASIBLE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from z3 import Solver, Int, Distinct, And, Or, Implies, sat, unsat

from .cegis import CEGISResult, CEGISRound, StepRecord, _estimate_pruned
from .geometry import Structure
from .verifiers import Verifier, default_chain
from .verifiers.base import PrecedenceConstraint


@dataclass
class Z3CEGISTrace:
    """Per-round record of the Z3 clause set (for blog visualisation)."""
    round_num: int
    proposed_plan: list[int] = field(default_factory=list)
    new_clauses: list[tuple[int, int]] = field(default_factory=list)
    total_clauses: int = 0


def _precedence_clause(action: list, a: int, b: int, n: int):
    """∀k. action[k]==b ⟹ ∃k'<k. action[k']==a"""
    return And([
        Implies(
            action[k] == b,
            Or([action[kp] == a for kp in range(k)]) if k > 0 else (1 == 0),
        )
        for k in range(n)
    ])


def solve_z3(
    structure: Structure,
    max_rounds: int = 200,
    friction: float = 0.7,
    verifiers: list[Verifier] | None = None,
    seed: int | None = 42,
) -> tuple[CEGISResult, list[Z3CEGISTrace]]:
    """CEGIS with Z3 as the plan proposer."""
    block_ids = [b.id for b in structure.blocks]
    n = len(block_ids)

    if verifiers is None:
        verifiers = default_chain(friction=friction)

    solver = Solver()
    if seed is not None:
        solver.set("random_seed", seed)

    # Action-indexed variables: action[k] is the block placed at step k.
    action = [Int(f"action_{k}") for k in range(n)]
    solver.add(Distinct(*action))
    for a in action:
        solver.add(Or([a == bid for bid in block_ids]))

    all_constraints: set[PrecedenceConstraint] = set()
    rounds: list[CEGISRound] = []
    z3_trace: list[Z3CEGISTrace] = []
    total_pruned = 0

    for round_num in range(max_rounds):
        status = solver.check()
        if status == unsat:
            return CEGISResult(
                feasible=False, sequence=None, rounds=rounds,
                constraints=list(all_constraints), total_pruned=total_pruned,
            ), z3_trace
        if status != sat:
            break

        model = solver.model()
        plan = [model.eval(action[k]).as_long() for k in range(n)]

        failure_step = None
        failed_block = None
        failed_verifier = None
        new_constraints: list[PrecedenceConstraint] = []
        step_records: list[StepRecord] = []

        for k in range(n):
            step_rec = StepRecord(step=k, block=plan[k])
            for v in verifiers:
                vr = v.check(structure, plan, k, block_ids)
                step_rec.verifier_results.append(vr)
                if not vr.feasible:
                    break
            step_records.append(step_rec)
            if not step_rec.feasible:
                failure_step = k
                failed_block = plan[k]
                failed_verifier = step_rec.failed_verifier
                for vr in step_rec.verifier_results:
                    if not vr.feasible:
                        for pc in vr.new_constraints:
                            if pc not in all_constraints:
                                new_constraints.append(pc)
                                all_constraints.add(pc)
                break

        # Add clauses. To prevent Z3 from re-proposing this exact plan even
        # when we learned no new precedence (can happen if the failing
        # verifier yields no constraints), add a blocking clause.
        new_clauses = []
        for pc in new_constraints:
            solver.add(_precedence_clause(action, pc.before, pc.after, n))
            new_clauses.append((pc.before, pc.after))
        if not new_constraints and failure_step is not None:
            solver.add(Or([action[k] != plan[k] for k in range(n)]))

        pruned = _estimate_pruned(n, len(new_constraints))
        total_pruned += pruned

        rounds.append(CEGISRound(
            round_num=round_num, candidate=plan, failure_step=failure_step,
            failed_block=failed_block, failed_verifier=failed_verifier,
            new_constraints=new_constraints, steps=step_records,
            pruned_count=pruned,
        ))
        z3_trace.append(Z3CEGISTrace(
            round_num=round_num, proposed_plan=plan,
            new_clauses=new_clauses, total_clauses=len(all_constraints),
        ))

        if failure_step is None:
            return CEGISResult(
                feasible=True, sequence=plan, rounds=rounds,
                constraints=list(all_constraints), total_pruned=total_pruned,
            ), z3_trace

    return CEGISResult(
        feasible=False, sequence=None, rounds=rounds,
        constraints=list(all_constraints), total_pruned=total_pruned,
    ), z3_trace
