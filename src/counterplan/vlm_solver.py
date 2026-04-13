"""VLM-as-proposer CEGIS.

Re-uses the agentic loop from `llm_solver.solve_llm` and replaces the text
layout description with a rendered PNG of the target structure, labelled
with block ids. The model sees the picture and the same `submit_plan` tool.

Requires FIREWORKS_API_KEY. Default model is kimi-k2p5 (supports tools +
image input per the Fireworks model table).
"""

from __future__ import annotations

import base64
import copy
import io
import os
import random

from .geometry import Structure
from .llm_solver import solve_llm


VLM_MODEL = os.environ.get("ASSEMBLY_VLM_MODEL", "accounts/fireworks/models/kimi-k2p5")


def render_structure_png(structure: Structure, size_px: int = 512) -> bytes:
    """Render the structure with labelled block ids onto a transparent PNG.

    Uses whatever `block.id` is set to at render time — so if the caller
    hands in a structure with permuted ids, the image shows the permuted
    labels, matching what the VLM will reason about.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    fig, ax = plt.subplots(figsize=(size_px / 100, size_px / 100), dpi=100)
    ax.set_aspect("equal")
    ax.set_facecolor("#fffff8")
    fig.patch.set_facecolor("#fffff8")

    xs, ys = [], []
    for b in structure.blocks:
        poly = mpatches.Polygon(
            b.vertices, closed=True,
            facecolor="#d7cfbf", edgecolor="#3b3a36", linewidth=1.5,
        )
        ax.add_patch(poly)
        cx, cy = b.vertices.mean(axis=0)
        ax.text(cx, cy, str(b.id), ha="center", va="center",
                fontsize=14, fontweight="bold", color="#111")
        xs.extend(b.vertices[:, 0])
        ys.extend(b.vertices[:, 1])

    pad = 0.5
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(structure.ground_y - pad, max(ys) + pad)
    ax.axhline(structure.ground_y, color="#888", linewidth=1)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"target structure — {len(structure.blocks)} blocks, gravity ↓",
                 fontsize=11, color="#3b3a36")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def solve_vlm(structure: Structure, max_rounds: int = 30,
              model: str = VLM_MODEL, verbose: bool = False,
              save_png_to: str | None = None,
              permute_ids: bool = True,
              permute_seed: int = 1234):
    """CEGIS with a VLM proposer: image in, plan out, verifier loop.

    Permutes block ids by default — the image shows permuted labels, so
    the comparison with the text-LLM runs is apples-to-apples.
    """
    # Build a shadow structure whose block.id fields carry the display
    # labels that will appear in the image.
    if permute_ids:
        real_ids = [b.id for b in structure.blocks]
        perm = list(real_ids)
        random.Random(permute_seed).shuffle(perm)
        shadow = copy.deepcopy(structure)
        for b, new in zip(shadow.blocks, perm):
            b.id = new
    else:
        shadow = structure

    png = render_structure_png(shadow)
    if save_png_to:
        with open(save_png_to, "wb") as f:
            f.write(png)

    b64 = base64.b64encode(png).decode()
    image_content = [{
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}"},
    }]
    # Feed solve_llm the original structure with permute_ids flag; solve_llm
    # handles the display↔real mapping internally, and the image we've
    # rendered is already in display-id space.
    return solve_llm(
        structure,
        max_rounds=max_rounds,
        model=model,
        verbose=verbose,
        image_content=image_content,
        permute_ids=permute_ids,
        permute_seed=permute_seed,
    )
