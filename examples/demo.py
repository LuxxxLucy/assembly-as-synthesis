#!/usr/bin/env python3
"""Full demo: CEGIS assembly planning + repair synthesis.

Runs the pipeline on multiple structures and generates all visualizations.
"""

import sys
sys.path.insert(0, 'src')

from counterplan.structures import arch_5, arch_7, unstable_tower, cantilever_5, pyramid_6, wall_4
from counterplan.stability import check_stability
from counterplan.cegis import solve as cegis_solve
from counterplan.repair import repair
from counterplan.viz import (
    plot_assembly_steps,
    plot_cegis_replay,
    plot_repair_comparison,
    plot_the_race,
    draw_structure,
)
import matplotlib.pyplot as plt


def demo_feasible():
    """Demo 1: CEGIS success — finds valid assembly sequence."""
    print("=" * 60)
    print("DEMO 1: Feasible Structures (CEGIS Success)")
    print("=" * 60)

    for name, s in [("Pyramid-6", pyramid_6()), ("Wall-4", wall_4())]:
        print(f"\n--- {name} ---")
        all_ids = [b.id for b in s.blocks]
        result = check_stability(s, all_ids)
        print(f"Full structure stable: {result.feasible}")

        cegis_result = cegis_solve(s, max_rounds=100, seed=42)
        print(f"CEGIS: {'FEASIBLE' if cegis_result.feasible else 'INFEASIBLE'}")
        print(f"  Rounds: {len(cegis_result.rounds)}")
        print(f"  Constraints: {len(cegis_result.constraints)}")
        if cegis_result.sequence:
            print(f"  Sequence: {cegis_result.sequence}")

            fig = plot_assembly_steps(s, cegis_result.sequence)
            fname = f'output/{name.lower()}_steps.png'
            fig.savefig(fname, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
            print(f"  Saved: {fname}")

            fig = plot_cegis_replay(cegis_result, s)
            fname = f'output/{name.lower()}_cegis.png'
            fig.savefig(fname, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
            print(f"  Saved: {fname}")

            fig = plot_the_race(cegis_result, len(s.blocks))
            fname = f'output/{name.lower()}_race.png'
            fig.savefig(fname, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
            print(f"  Saved: {fname}")

        plt.close('all')


def demo_arch_infeasible():
    """Demo 2: Arches are inherently infeasible for sequential assembly.

    This is the key insight: a semicircular arch requires mutual thrust
    between voussoirs — no single block can stand alone without the others.
    CEGIS correctly identifies cyclic dependencies and declares INFEASIBLE.
    """
    print("\n" + "=" * 60)
    print("DEMO 2: Arches — Inherently Infeasible (Cyclic Dependencies)")
    print("=" * 60)

    for name, s in [("Arch-5", arch_5()), ("Arch-7", arch_7())]:
        print(f"\n--- {name} ---")
        all_ids = [b.id for b in s.blocks]
        result = check_stability(s, all_ids)
        print(f"Full structure stable: {result.feasible}")

        cegis_result = cegis_solve(s, max_rounds=50, seed=42)
        print(f"CEGIS: {'FEASIBLE' if cegis_result.feasible else 'INFEASIBLE'}")
        print(f"  Rounds: {len(cegis_result.rounds)}")
        print(f"  Constraints: {len(cegis_result.constraints)}")
        for c in cegis_result.constraints:
            print(f"    {c.before} ≺ {c.after}")

        fig = plot_cegis_replay(cegis_result, s)
        fname = f'output/{name.lower()}_cegis.png'
        fig.savefig(fname, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
        print(f"  Saved: {fname}")

        # Attempt repair
        if not cegis_result.feasible:
            print(f"  Attempting repair synthesis...")
            repair_result = repair(s, cegis_result, max_displacement=0.8, max_iterations=20)
            print(f"  Repair: {'SUCCEEDED' if repair_result.success else 'FAILED'}")
            if repair_result.success:
                print(f"  Displacement: {repair_result.displacement_norm:.4f}")
                print(f"  New sequence: {repair_result.feasible_sequence}")
                fig = plot_repair_comparison(repair_result)
                if fig:
                    fname = f'output/{name.lower()}_repair.png'
                    fig.savefig(fname, dpi=150, bbox_inches='tight',
                               facecolor=fig.get_facecolor())
                    print(f"  Saved: {fname}")

        plt.close('all')


def demo_repair_synthesis():
    """Demo 3: Repair synthesis on structures with solvable infeasibility."""
    print("\n" + "=" * 60)
    print("DEMO 3: Repair Synthesis")
    print("=" * 60)

    for name, s, max_d in [("Tower", unstable_tower(), 0.5),
                            ("Cantilever", cantilever_5(), 0.8)]:
        print(f"\n--- {name} ---")
        cegis_result = cegis_solve(s, max_rounds=50, seed=42)
        print(f"CEGIS: {'FEASIBLE' if cegis_result.feasible else 'INFEASIBLE'}")
        print(f"  Rounds: {len(cegis_result.rounds)}")

        if not cegis_result.feasible:
            repair_result = repair(s, cegis_result, max_displacement=max_d, max_iterations=20)
            print(f"  Repair: {'SUCCEEDED' if repair_result.success else 'FAILED'}")
            if repair_result.success:
                print(f"  Iterations: {repair_result.iterations}")
                print(f"  Displacement: {repair_result.displacement_norm:.4f}")
                print(f"  Sequence: {repair_result.feasible_sequence}")

                fig = plot_repair_comparison(repair_result)
                if fig:
                    fname = f'output/{name.lower()}_repair.png'
                    fig.savefig(fname, dpi=150, bbox_inches='tight',
                               facecolor=fig.get_facecolor())
                    print(f"  Saved: {fname}")

        plt.close('all')


def demo_gallery():
    """Gallery view of all structures."""
    print("\n" + "=" * 60)
    print("DEMO 4: Structure Gallery")
    print("=" * 60)

    structs = [
        ("Wall 4", wall_4()),
        ("Pyramid 6", pyramid_6()),
        ("Arch 5", arch_5()),
        ("Arch 7", arch_7()),
        ("Tower", unstable_tower()),
        ("Cantilever", cantilever_5()),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    for ax, (name, s) in zip(axes.flat, structs):
        all_ids = [b.id for b in s.blocks]
        result = check_stability(s, all_ids)
        status = '✓' if result.feasible else '✗'
        draw_structure(ax, s, stability_result=result, title=f'{name} {status}')

    fig.suptitle('Test Structure Gallery', color='#D8DEE9',
                fontsize=18, fontweight='bold')
    plt.tight_layout()
    fig.savefig('output/gallery.png', dpi=150, bbox_inches='tight',
               facecolor=fig.get_facecolor())
    print("  Saved: output/gallery.png")
    plt.close('all')


if __name__ == '__main__':
    import os
    os.makedirs('output', exist_ok=True)

    demo_gallery()
    demo_feasible()
    demo_arch_infeasible()
    demo_repair_synthesis()

    print("\n" + "=" * 60)
    print("All demos complete. Check output/ for visualizations.")
    print("=" * 60)
