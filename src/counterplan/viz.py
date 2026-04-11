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


# Polar Void palette — cold, austere, near-neutral
COLORS = {
    'bg': '#1A1D23',
    'fg': '#D8DEE9',
    'blue': '#7BA4C7',
    'cyan': '#88C0D0',
    'green': '#8FBCA3',
    'yellow': '#D4A76A',
    'orange': '#D97757',       # Anthropic terracotta — active element accent
    'red': '#BF616A',
    'purple': '#B48EAD',
    'light_bg': '#22262E',
    'surface': '#2A2F3A',
    'ground': '#3B4048',
    'muted': '#6B7894',
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


# ── Animated CEGIS negotiation replay ───────────────────────────

def animate_negotiation_replay(
    cegis_result: CEGISResult,
    structure: Structure,
    save_path: str | None = None,
    fps: int = 24,
) -> animation.FuncAnimation:
    """Animated CEGIS negotiation: propose → place → fail → learn → rewind → retry.

    Each round shows blocks appearing one by one, failure flash, constraint
    annotation, and rewind. The final round (if successful) shows the full
    assembly with a success pulse.

    Produces ~30s at 24fps. Output: MP4 (ffmpeg) or GIF (pillow).
    """
    rounds = cegis_result.rounds
    n_blocks = len(structure.blocks)

    # ── Build frame timeline ──
    # Each round has phases: PROPOSE, PLACE×k, FAIL (or SUCCESS), LEARN, REWIND
    PROPOSE_FRAMES = int(1.0 * fps)    # 1s
    PLACE_FRAMES = int(0.6 * fps)      # 0.6s per block placement
    FAIL_FRAMES = int(0.8 * fps)       # 0.8s failure flash
    LEARN_FRAMES = int(1.0 * fps)      # 1s constraint display
    REWIND_FRAMES = int(0.8 * fps)     # 0.8s rewind
    SUCCESS_FRAMES = int(1.5 * fps)    # 1.5s success hold
    PAUSE_FRAMES = int(0.3 * fps)      # 0.3s between rounds

    # Pre-compute frame plan: list of (round_idx, phase, sub_frame, block_idx)
    frame_plan = []

    for ri, rd in enumerate(rounds):
        n_steps = rd.failure_step if rd.failure_step is not None else len(rd.candidate)

        # Propose phase
        for f in range(PROPOSE_FRAMES):
            frame_plan.append(('propose', ri, f / PROPOSE_FRAMES, -1))

        # Place blocks one by one
        for step in range(n_steps):
            for f in range(PLACE_FRAMES):
                frame_plan.append(('place', ri, f / PLACE_FRAMES, step))

        if rd.failure_step is not None:
            # Fail phase
            for f in range(FAIL_FRAMES):
                frame_plan.append(('fail', ri, f / FAIL_FRAMES, rd.failure_step))
            # Learn phase
            for f in range(LEARN_FRAMES):
                frame_plan.append(('learn', ri, f / LEARN_FRAMES, rd.failure_step))
            # Rewind phase
            for f in range(REWIND_FRAMES):
                frame_plan.append(('rewind', ri, f / REWIND_FRAMES, n_steps))
            # Pause
            for f in range(PAUSE_FRAMES):
                frame_plan.append(('pause', ri, 0, 0))
        else:
            # Success — place remaining blocks
            for step in range(n_steps, len(rd.candidate)):
                for f in range(PLACE_FRAMES):
                    frame_plan.append(('place', ri, f / PLACE_FRAMES, step))
            # Hold success
            for f in range(SUCCESS_FRAMES):
                frame_plan.append(('success', ri, f / SUCCESS_FRAMES, len(rd.candidate)))

    total_frames = len(frame_plan)

    # ── Setup figure ──
    fig = plt.figure(figsize=(14, 8))
    fig.set_facecolor(COLORS['bg'])
    # Structure viewport (left 70%)
    ax_struct = fig.add_axes([0.02, 0.12, 0.65, 0.82])
    # Info panel (right 30%)
    ax_info = fig.add_axes([0.70, 0.12, 0.28, 0.82])
    # Progress bar (bottom)
    ax_progress = fig.add_axes([0.02, 0.02, 0.96, 0.06])

    # Accumulated constraints across rounds
    all_constraints = []

    def update(frame_idx):
        if frame_idx >= len(frame_plan):
            return

        phase, ri, t, step_or_block = frame_plan[frame_idx]
        rd = rounds[ri]

        # ── Clear axes ──
        ax_struct.clear()
        ax_info.clear()
        ax_progress.clear()

        # ── Structure viewport ──
        setup_axes(ax_struct, structure)

        if phase == 'propose':
            # Show all blocks as ghosts, sequence text fading in
            for block in structure.blocks:
                draw_block(ax_struct, block, color='none', alpha=0.15 + 0.15 * t,
                          edge_color=COLORS['muted'], edge_width=0.5, label=True)
            ax_struct.set_title(f'Round {ri + 1}: proposing sequence...',
                              color=COLORS['fg'], fontsize=13, fontweight='bold', pad=10)

        elif phase == 'place':
            # Show placed blocks solid, current block descending
            placed_so_far = rd.candidate[:step_or_block]
            for block in structure.blocks:
                if block.id in placed_so_far:
                    draw_block(ax_struct, block, color=COLORS['blue'], alpha=0.85)
                elif block.id == rd.candidate[step_or_block]:
                    # Current block: descending animation
                    offset_y = (1 - t) * 0.5  # descend from 0.5 units above
                    shifted_verts = block.vertices.copy()
                    shifted_verts[:, 1] += offset_y
                    temp_block = Block(id=block.id, vertices=shifted_verts, mass=block.mass)
                    alpha = 0.4 + 0.45 * t
                    draw_block(ax_struct, temp_block, color=COLORS['orange'], alpha=alpha)
                else:
                    draw_block(ax_struct, block, color='none', alpha=0.1,
                              edge_color=COLORS['muted'], edge_width=0.3, label=False)
            ax_struct.set_title(
                f'Round {ri + 1}, Step {step_or_block + 1}: placing block {rd.candidate[step_or_block]}',
                color=COLORS['orange'], fontsize=13, fontweight='bold', pad=10)

        elif phase == 'fail':
            # Show placed blocks + failed block flashing red
            placed_so_far = rd.candidate[:step_or_block]
            for block in structure.blocks:
                if block.id in placed_so_far:
                    draw_block(ax_struct, block, color=COLORS['blue'], alpha=0.85)
                elif block.id == rd.candidate[step_or_block]:
                    # Flash red: pulse 3 times
                    pulse = abs(np.sin(t * 3 * np.pi))
                    color = COLORS['red'] if pulse > 0.5 else COLORS['light_bg']
                    draw_block(ax_struct, block, color=color, alpha=0.9)
                else:
                    draw_block(ax_struct, block, color='none', alpha=0.1,
                              edge_color=COLORS['muted'], edge_width=0.3, label=False)
            ax_struct.set_title(
                f'Round {ri + 1}: block {rd.candidate[step_or_block]} UNSTABLE',
                color=COLORS['red'], fontsize=13, fontweight='bold', pad=10)

        elif phase == 'learn':
            # Show placed + failed block in red, constraint text appearing
            placed_so_far = rd.candidate[:step_or_block]
            for block in structure.blocks:
                if block.id in placed_so_far:
                    draw_block(ax_struct, block, color=COLORS['blue'], alpha=0.85)
                elif block.id == rd.candidate[step_or_block]:
                    draw_block(ax_struct, block, color=COLORS['red'], alpha=0.6)
                else:
                    draw_block(ax_struct, block, color='none', alpha=0.1,
                              edge_color=COLORS['muted'], edge_width=0.3, label=False)
            # Draw constraint arrows
            for pc in rd.new_constraints:
                b_before = structure.block_by_id(pc.before)
                b_after = structure.block_by_id(pc.after)
                if b_before and b_after:
                    ax_struct.annotate('',
                        xy=b_after.centroid, xytext=b_before.centroid,
                        arrowprops=dict(arrowstyle='->', color=COLORS['orange'],
                                        lw=2.0 * t, mutation_scale=12, alpha=t))
            ax_struct.set_title(
                f'Round {ri + 1}: learning constraints',
                color=COLORS['orange'], fontsize=13, fontweight='bold', pad=10)

        elif phase == 'rewind':
            # Blocks fade out in reverse
            n_placed = step_or_block
            n_visible = int(n_placed * (1 - t))
            placed_so_far = rd.candidate[:n_visible]
            for block in structure.blocks:
                if block.id in placed_so_far:
                    draw_block(ax_struct, block, color=COLORS['blue'], alpha=0.5 * (1 - t))
                else:
                    draw_block(ax_struct, block, color='none', alpha=0.08,
                              edge_color=COLORS['muted'], edge_width=0.3, label=False)
            ax_struct.set_title(f'Round {ri + 1}: rewinding...',
                              color=COLORS['muted'], fontsize=13, pad=10)

        elif phase == 'pause':
            for block in structure.blocks:
                draw_block(ax_struct, block, color='none', alpha=0.1,
                          edge_color=COLORS['muted'], edge_width=0.3, label=False)
            ax_struct.set_title('', color=COLORS['fg'])

        elif phase == 'success':
            # All blocks placed with subtle pulse
            pulse = 0.85 + 0.15 * abs(np.sin(t * 2 * np.pi))
            for block in structure.blocks:
                draw_block(ax_struct, block, color=COLORS['blue'], alpha=pulse)
            ax_struct.set_title(f'Round {ri + 1}: STABLE — assembly sequence found',
                              color=COLORS['green'], fontsize=13, fontweight='bold', pad=10)

        # ── Info panel ──
        ax_info.set_facecolor(COLORS['bg'])
        ax_info.set_xlim(0, 1)
        ax_info.set_ylim(0, 1)
        ax_info.axis('off')

        y = 0.95
        ax_info.text(0.05, y, f'Round {ri + 1}/{len(rounds)}',
                    color=COLORS['fg'], fontsize=12, fontweight='bold',
                    family='monospace', transform=ax_info.transAxes)
        y -= 0.06

        # Show current sequence
        ax_info.text(0.05, y, 'Sequence:', color=COLORS['muted'], fontsize=9,
                    family='monospace', transform=ax_info.transAxes)
        y -= 0.04
        seq_str = ' '.join(str(b) for b in rd.candidate)
        ax_info.text(0.05, y, seq_str, color=COLORS['fg'], fontsize=9,
                    family='monospace', transform=ax_info.transAxes)
        y -= 0.08

        # Show accumulated constraints
        ax_info.text(0.05, y, 'Constraints:', color=COLORS['muted'], fontsize=9,
                    family='monospace', transform=ax_info.transAxes)
        y -= 0.04

        # Collect all constraints up to current round
        shown_constraints = set()
        for prev_rd in rounds[:ri + 1]:
            for pc in prev_rd.new_constraints:
                shown_constraints.add((pc.before, pc.after))

        for (before, after) in sorted(shown_constraints):
            is_new = any(pc.before == before and pc.after == after for pc in rd.new_constraints)
            color = COLORS['orange'] if (is_new and phase in ('learn', 'fail')) else COLORS['fg']
            ax_info.text(0.07, y, f'{before} → {after}', color=color, fontsize=9,
                        family='monospace', transform=ax_info.transAxes)
            y -= 0.035
            if y < 0.1:
                break

        # ── Progress bar ──
        ax_progress.set_facecolor(COLORS['light_bg'])
        ax_progress.set_xlim(0, 1)
        ax_progress.set_ylim(0, 1)
        ax_progress.axis('off')

        progress = frame_idx / max(total_frames - 1, 1)
        bar_color = COLORS['green'] if phase == 'success' else COLORS['blue']
        ax_progress.add_patch(patches.Rectangle(
            (0, 0.1), progress, 0.8,
            facecolor=bar_color, alpha=0.6, edgecolor='none'))

    anim = animation.FuncAnimation(
        fig, update, frames=total_frames, interval=1000 // fps, repeat=False,
    )

    if save_path:
        writer = 'ffmpeg' if save_path.endswith('.mp4') else 'pillow'
        dpi = 150 if save_path.endswith('.mp4') else 100
        anim.save(save_path, writer=writer, fps=fps, dpi=dpi)

    return anim
