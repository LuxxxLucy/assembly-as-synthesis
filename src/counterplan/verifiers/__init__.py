"""Verifier chain: extensible per-step checks for CEGIS assembly planning.

Each verifier independently checks a candidate sequence at a given step and
returns a VerifierResult. The CEGIS loop runs verifiers in order; the first
failure learns its precedence constraints and triggers a rewind.

Adding a new verifier (e.g. robot reachability, footprint, no-flip) is a
drop-in extension — no changes to CEGIS or the trace format.
"""

from __future__ import annotations

from .base import Verifier, VerifierResult
from .stability import StabilityVerifier
from .kinematic import KinematicVerifier
from .landing import LandingVerifier


def default_chain(friction: float = 0.7) -> list[Verifier]:
    """The default verifier chain used by cegis.solve().

    Order (cheapest-first / kinematic-first):
      1. KinematicVerifier  — fall-path clearance (geometric, no LP)
      2. StabilityVerifier  — static equilibrium under gravity + friction (LP)
      3. LandingVerifier    — block actually settles at target (geometric)
    """
    return [
        KinematicVerifier(),
        StabilityVerifier(friction=friction),
        LandingVerifier(),
    ]


__all__ = [
    "Verifier",
    "VerifierResult",
    "StabilityVerifier",
    "KinematicVerifier",
    "LandingVerifier",
    "default_chain",
]
