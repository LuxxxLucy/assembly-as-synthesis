"""Verifier protocol: each verifier is a per-step check.

A verifier is called once per assembly step with (structure, sequence, step).
It returns VerifierResult; if infeasible, it attaches precedence constraints
that will be fed back into the next CEGIS proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..geometry import Structure


@dataclass
class PrecedenceConstraint:
    """Block `before` must be placed before block `after`.

    `source` identifies which verifier produced this constraint (for visualization
    and ablation — e.g. "stability" vs "kinematic").
    """
    before: int
    after: int
    source: str = ""
    reason: str = ""

    def __hash__(self) -> int:
        return hash((self.before, self.after, self.source))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PrecedenceConstraint):
            return False
        return (
            self.before == other.before
            and self.after == other.after
            and self.source == other.source
        )


@dataclass
class VerifierResult:
    """Outcome of a single verifier invocation at one assembly step."""
    verifier: str
    feasible: bool
    new_constraints: list[PrecedenceConstraint] = field(default_factory=list)
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Verifier(Protocol):
    """Per-step check returning pass/fail + learned precedence constraints."""

    name: str

    def check(
        self,
        structure: Structure,
        sequence: list[int],
        step: int,
        all_block_ids: list[int],
    ) -> VerifierResult:
        ...
