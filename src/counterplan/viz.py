"""Visualization for assembly sequence planning and repair synthesis.

Provides matplotlib-based visualizations:
  - Structure rendering with stability aura (block-level heatmap)
  - Step-by-step assembly sequence animation
  - CEGIS negotiation replay (propose → fail → rewind → reroute)
  - Repair synthesis before/after comparison
  - The Race: CEGIS vs brute force progress
"""

from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize
from matplotlib import cm
import matplotlib.animation as animation

from .geometry import Block, Structure, Contact
from .stability import check_stability, StabilityResult
from .cegis import CEGISResult, CEGISRound
from .repair import RepairResult


# Nord-inspired palette
COLORS = {
    'bg': '#2E3440',
    'fg': '#D8DEE9',
    'blue': '#5E81AC',
    'cyan': '#88C0D0',
    'green': '#A3BE8C',
    'yellow': '#EBCB8B',
    'orange': '#D08770',
    'red': '#BF616A',
    'purple': '#B48EAD',
    'light_bg': '#3B4252',
    'ground': '#4C566A',
}


def setup_axes(ax: plt.Axes, structure: Structure, title: str = ''):
    """Configure axes with dark theme and proper bounds."""
    ax.set_facecolor(COLORS['bg'])
    ax.figure.set_facecolor(COLORS['bg'])

    # Compute bounds from structure
    all_verts = np.vstack([b.vertices for b in structure.blocks])
    margin = 1.0
    ax.set_xlim(all_verts[:, 0].min() - margin, all_verts[:, 0].max() + margin)
    ax.set_ylim(structure.ground_y - 0.5, all_verts[:, 1].max() + margin)
    ax.set_aspect('equal')

    # Ground
    xlim = ax.get_xlim()
    ground = patches.Rectangle(
        (xlim[0], structure.ground_y - 0.5), xlim[1] - xlim[0], 0.5,
        facecolor=COLORS['ground'], edgecolor='none',
    )
    ax.add_patch(ground)

    # Style
    ax.spines[:].set_visible(False)
    ax.tick_params(colors=COLORS['fg'], labelsize=8)
    if title:
        ax.set_title(title, color=COLORS['fg'], fontsize=14, fontweight='bold', pad=12)


def draw_block(
    ax: plt.Axes, block: Block,
    color: str = '#5E81AC', alpha: float = 0.85,
    edge_color: str = '#D8DEE9', edge_width: float = 1.5,
    label: bool = True,
):
    """Draw a single block."""
    poly = plt.Polygon(
        block.vertices, closed=True,
        facecolor=color, edgecolor=edge_color,
        linewidth=edge_width, alpha=alpha,
    )
    ax.add_patch(poly)

    if label:
        cx, cy = block.centroid
        ax.text(cx, cy, str(block.id), ha='center', va='center',
                color=COLORS['fg'], fontsize=11, fontweight='bold')


def draw_structure(
    ax: plt.Axes, structure: Structure,
    placed_ids: list[int] | None = None,
    stability_result: StabilityResult | None = None,
    title: str = '',
):
    """Draw the full structure with optional stability heatmap."""
    setup_axes(ax, structure, title)

    if placed_ids is None:
        placed_ids = [b.id for b in structure.blocks]

    for block in structure.blocks:
        if block.id in placed_ids:
            if stability_result and stability_result.block_margins:
                margin = stability_result.block_margins.get(block.id, 0.5)
                color = _margin_to_color(margin)
            else:
                color = COLORS['blue']
            draw_block(ax, block, color=color)
        else:
            # Ghost: unplaced blocks shown as outlines
            draw_block(ax, block, color='none', alpha=0.3,
                      edge_color=COLORS['fg'], edge_width=0.5, label=False)

    # Draw contacts if stability result available
    if stability_result and stability_result.contact_forces is not None:
        contacts = structure.detect_contacts(placed_ids)
        _draw_contact_forces(ax, contacts, stability_result.contact_forces)


def _margin_to_color(margin: float) -> str:
    """Map stability margin [0, 1+] to blue→green→yellow→red gradient."""
    # Clamp to [0, 1]
    m = max(0.0, min(1.0, margin))
    if m > 0.6:
        return COLORS['blue']
    elif m > 0.3:
        return COLORS['cyan']
    elif m > 0.1:
        return COLORS['yellow']
    elif m > 0.0:
        return COLORS['orange']
    else:
        return COLORS['red']


def _draw_contact_forces(ax: plt.Axes, contacts: list[Contact], forces: np.ndarray):
    """Draw contact force arrows."""
    scale = 0.15
    for i, (c, f) in enumerate(zip(contacts, forces)):
        fn, ft = f
        if abs(fn) < 1e-6:
            continue
        # Normal force arrow
        force_vec = fn * c.normal * scale
        ax.annotate('', xy=c.point + force_vec, xytext=c.point,
                    arrowprops=dict(arrowstyle='->', color=COLORS['green'],
                                    lw=1.5, mutation_scale=8))
        # Contact point
        ax.plot(*c.point, 'o', color=COLORS['green'], markersize=3, alpha=0.7)


# ── Assembly sequence animation ──────────────────────────────────

def animate_assembly(
    structure: Structure,
    sequence: list[int],
    save_path: str | None = None,
    interval: int = 800,
) -> animation.FuncAnimation:
    """Create step-by-step assembly animation."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 7))

    def update(frame):
        ax.clear()
        step = frame
        placed = sequence[:step + 1]

        # Check stability at this step
        result = check_stability(structure, placed)

        title = f'Step {step + 1}/{len(sequence)}: place block {sequence[step]}'
        if not result.feasible:
            title += '  ✗ UNSTABLE'
        draw_structure(ax, structure, placed, result, title)

    anim = animation.FuncAnimation(
        fig, update, frames=len(sequence), interval=interval, repeat=True,
    )

    if save_path:
        anim.save(save_path, writer='pillow', fps=1000 // interval)

    return anim


# ── CEGIS negotiation replay ─────────────────────────────────────

def plot_cegis_replay(cegis_result: CEGISResult, structure: Structure):
    """Plot the CEGIS negotiation: each round as a row showing the attempt and failure point."""
    rounds = cegis_result.rounds
    n_rounds = min(len(rounds), 8)  # show at most 8 rounds

    fig, axes = plt.subplots(n_rounds, 1, figsize=(12, 3 * n_rounds))
    fig.set_facecolor(COLORS['bg'])

    if n_rounds == 1:
        axes = [axes]

    for i, (ax, rd) in enumerate(zip(axes, rounds[:n_rounds])):
        ax.set_facecolor(COLORS['bg'])
        n_blocks = len(structure.blocks)

        # Draw sequence as colored bar chart
        for j, bid in enumerate(rd.candidate):
            if rd.failure_step is not None and j == rd.failure_step:
                color = COLORS['red']
                ax.axvline(x=j, color=COLORS['red'], alpha=0.3, linewidth=20)
            elif rd.failure_step is not None and j > rd.failure_step:
                color = COLORS['light_bg']
            else:
                color = COLORS['blue']
            ax.barh(0, 0.8, left=j, height=0.6, color=color, edgecolor=COLORS['fg'], linewidth=0.5)
            ax.text(j + 0.4, 0, str(bid), ha='center', va='center',
                    color=COLORS['fg'], fontsize=10, fontweight='bold')

        # Labels
        status = '✓' if rd.failure_step is None else f'✗ step {rd.failure_step}'
        ax.set_xlim(-0.2, n_blocks + 0.2)
        ax.set_ylim(-0.5, 0.5)
        ax.set_yticks([])
        ax.spines[:].set_visible(False)
        ax.tick_params(colors=COLORS['fg'], labelsize=8)

        label = f'Round {rd.round_num + 1}: {status}'
        if rd.new_constraints:
            constrs = ', '.join(f'{c.before}≺{c.after}' for c in rd.new_constraints)
            label += f'  →  learned: {constrs}'
        ax.set_ylabel(label, color=COLORS['fg'], fontsize=9, rotation=0,
                     labelpad=120, va='center')

    axes[-1].set_xlabel('Assembly step', color=COLORS['fg'], fontsize=11)
    fig.suptitle('CEGIS Negotiation Replay', color=COLORS['fg'],
                fontsize=16, fontweight='bold', y=0.98)
    plt.tight_layout()
    return fig


# ── Repair synthesis comparison ──────────────────────────────────

def plot_repair_comparison(repair_result: RepairResult):
    """Side-by-side: original (infeasible) vs repaired (feasible) structure."""
    if not repair_result.success or repair_result.repaired_structure is None:
        print("Repair was not successful — nothing to compare.")
        return None

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

    orig = repair_result.original_structure
    repaired = repair_result.repaired_structure

    # Original (infeasible)
    draw_structure(ax1, orig, title='Original — INFEASIBLE')
    # Mark critical blocks in red
    if repair_result.vertex_displacements:
        for bid in repair_result.vertex_displacements:
            block = orig.block_by_id(bid)
            draw_block(ax1, block, color=COLORS['red'], alpha=0.5, edge_width=2.5)

    # Repaired (feasible)
    if repair_result.feasible_sequence:
        result = check_stability(repaired, repair_result.feasible_sequence)
    else:
        result = None
    draw_structure(ax2, repaired, stability_result=result,
                  title=f'Repaired — FEASIBLE (Δ={repair_result.displacement_norm:.3f})')

    # Draw displacement arrows
    if repair_result.vertex_displacements:
        for bid, dp in repair_result.vertex_displacements.items():
            orig_block = orig.block_by_id(bid)
            for v, d in zip(orig_block.vertices, dp):
                if np.linalg.norm(d) > 0.01:
                    ax2.annotate('', xy=v + d, xytext=v,
                                arrowprops=dict(arrowstyle='->', color=COLORS['orange'],
                                                lw=2, mutation_scale=10))

    fig.suptitle('Repair Synthesis: Minimal Geometry Modification',
                color=COLORS['fg'], fontsize=16, fontweight='bold')
    plt.tight_layout()
    return fig


# ── The Race visualization ───────────────────────────────────────

def plot_the_race(cegis_result: CEGISResult, n_blocks: int):
    """Animated comparison: CEGIS rounds vs brute force permutation count."""
    import math

    total_perms = math.factorial(n_blocks)
    cegis_rounds = len(cegis_result.rounds)

    fig, ax = plt.subplots(figsize=(12, 4))
    fig.set_facecolor(COLORS['bg'])
    ax.set_facecolor(COLORS['bg'])

    # Brute force bar (showing how far it would get)
    brute_checked = sum(
        r.failure_step + 1 if r.failure_step is not None else n_blocks
        for r in cegis_result.rounds
    )
    brute_frac = brute_checked / total_perms

    ax.barh(1, brute_frac * 100, height=0.4, color=COLORS['red'], alpha=0.8,
            edgecolor=COLORS['fg'], linewidth=0.5)
    ax.text(brute_frac * 100 + 2, 1,
            f'Brute force: {brute_checked:,} / {total_perms:,} checked ({brute_frac*100:.1f}%)',
            va='center', color=COLORS['red'], fontsize=11)

    # CEGIS bar
    ax.barh(0, 100, height=0.4, color=COLORS['blue'], alpha=0.8,
            edgecolor=COLORS['fg'], linewidth=0.5)
    ax.text(50, 0, f'CEGIS: {cegis_rounds} rounds', ha='center', va='center',
            color=COLORS['fg'], fontsize=12, fontweight='bold')

    ax.set_xlim(-5, 110)
    ax.set_ylim(-0.5, 1.8)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(['CEGIS', 'Brute force'], color=COLORS['fg'], fontsize=12)
    ax.spines[:].set_visible(False)
    ax.tick_params(colors=COLORS['fg'])
    ax.set_xlabel('Progress (%)', color=COLORS['fg'], fontsize=11)
    ax.set_title(f'{cegis_rounds} rounds vs {total_perms:,} permutations',
                color=COLORS['fg'], fontsize=14, fontweight='bold')

    plt.tight_layout()
    return fig


# ── Step-by-step stability aura ──────────────────────────────────

def plot_assembly_steps(structure: Structure, sequence: list[int]):
    """Plot each assembly step as a subplot with stability aura."""
    n = len(sequence)
    cols = min(n, 4)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    fig.set_facecolor(COLORS['bg'])

    if n == 1:
        axes = np.array([[axes]])
    axes = np.atleast_2d(axes)

    for step in range(n):
        r, c = divmod(step, cols)
        ax = axes[r, c]

        placed = sequence[:step + 1]
        result = check_stability(structure, placed)

        status = '✓' if result.feasible else '✗'
        draw_structure(ax, structure, placed, result,
                      title=f'Step {step+1}: +{sequence[step]} {status}')

    # Hide unused axes
    for step in range(n, rows * cols):
        r, c = divmod(step, cols)
        axes[r, c].set_visible(False)

    fig.suptitle('Assembly Sequence with Stability Aura',
                color=COLORS['fg'], fontsize=16, fontweight='bold', y=1.02)
    plt.tight_layout()
    return fig
