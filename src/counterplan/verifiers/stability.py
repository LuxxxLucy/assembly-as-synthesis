"""Stability verifier: LP-based static equilibrium check.

Wraps the existing check_stability + find_minimal_support_set logic in the
Verifier protocol. On failure, learns the minimal set of absent blocks that
must precede the failing block for equilibrium.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..geometry import Structure
from ..stability import check_stability_at_step, find_minimal_support_set
from .base import Verifier, VerifierResult, PrecedenceConstraint


@dataclass
class StabilityVerifier:
    name: str = "stability"
    friction: float = 0.7

    def check(
        self,
        structure: Structure,
        sequence: list[int],
        step: int,
        all_block_ids: list[int],
    ) -> VerifierResult:
        stab = check_stability_at_step(structure, sequence, step, self.friction)

        diagnostics = {
            "feasible": stab.feasible,
            "margin": stab.margin if stab.feasible else None,
            "block_margins": stab.block_margins,
        }

        if stab.feasible:
            return VerifierResult(
                verifier=self.name, feasible=True, diagnostics=diagnostics,
            )

        failed_block = sequence[step]
        placed_before = sequence[:step]
        support_set = find_minimal_support_set(
            structure, failed_block, placed_before, all_block_ids, self.friction,
        )

        constraints = [
            PrecedenceConstraint(
                before=sb,
                after=failed_block,
                source=self.name,
                reason=f"{sb} must support {failed_block}",
            )
            for sb in support_set
        ]

        return VerifierResult(
            verifier=self.name,
            feasible=False,
            new_constraints=constraints,
            reason=f"block {failed_block} unstable without {support_set}",
            diagnostics=diagnostics,
        )
