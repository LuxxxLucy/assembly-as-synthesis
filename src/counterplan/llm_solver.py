"""LLM-as-proposer CEGIS via tool calls.

The LLM sees one tool, `submit_plan`, whose argument is a full permutation
of block ids. Each turn, the LLM calls the tool. We intercept the call,
run the verifier chain on the proposed plan, and return the verifier's
feedback as the `role: tool` response. The LLM then gets another turn
with that feedback appended to its context — no prose history to
reconstruct, no parse errors to chase.

Transport: Fireworks OpenAI-compatible Chat Completions endpoint. Set
FIREWORKS_API_KEY in the environment. Default model is deepseek-v3p2.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

from .cegis import CEGISResult, CEGISRound, StepRecord, _estimate_pruned
from .geometry import Structure
from .verifiers import Verifier, default_chain


FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
LLM_MODEL = os.environ.get("ASSEMBLY_LLM_MODEL", "accounts/fireworks/models/deepseek-v3p1")

SUBMIT_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_plan",
        "description": (
            "Submit an assembly plan: the order in which to place the blocks. "
            "The physics verifier will check it step by step and reply with "
            "pass or the first failing step and why. Call this tool repeatedly "
            "until the verifier accepts the plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "The full placement order: a permutation of every block id, "
                        "each appearing exactly once."
                    ),
                },
            },
            "required": ["plan"],
        },
    },
}

SYSTEM_PROMPT = """You are a physical-assembly planner. You are given a set of
rigid blocks laid out in their target positions. Output the order in which a
robot should place them so that, after every placement:

  (a) the block can descend straight down from above without colliding with
      blocks already placed (kinematic reachability),
  (b) the partial structure stands under gravity with friction and
      compression-only contact (static stability), and
  (c) the block settles onto what is already there, rather than falling past.

Rules of thumb:
  * Place lower blocks before the blocks that rest on them.
  * Place side / supporting blocks before arches, lintels, or keystones.
  * If block B's drop path crosses block A's final position, place B before A.

You interact via the `submit_plan` tool. Each time you call it, the verifier
replies with either `ACCEPTED` (you are done) or a structured failure message
telling you which step and which block broke which check, plus any learned
precedence constraints. Use that feedback to propose a better plan the next
turn. Keep calling the tool until you succeed."""


@dataclass
class LLMCallTrace:
    round_num: int
    plan: list[int] | None
    verifier_message: str
    raw_response_id: str | None = None


def _describe_structure_basic(structure: Structure) -> str:
    """Minimal description: id + contact neighbours, shuffled listing.

    Deliberately no coordinates, no layout verbs, no "who sits on whom".
    The LLM has the topology of the contact graph and nothing else; the
    verifier loop has to teach it the ordering. Trajectory should look
    like random CEGIS — the LLM has no prior advantage when all it sees
    is an undirected graph with anonymous labels.
    """
    import random
    contacts: dict[int, list[int]] = {b.id: [] for b in structure.blocks}
    for c in structure.detect_contacts():
        if c.block_a in contacts and c.block_b in contacts:
            contacts[c.block_a].append(c.block_b)
            contacts[c.block_b].append(c.block_a)
    rng = random.Random(1234)
    shuffled = list(structure.blocks)
    rng.shuffle(shuffled)
    lines = ["Blocks (id, contact neighbours):"]
    for b in shuffled:
        nbrs = sorted(set(contacts[b.id]))
        lines.append(f"  id={b.id} neighbors={nbrs}")
    lines.append(
        "No coordinates are given, and no information about which block is "
        "above which. Block ids are arbitrary labels and do NOT imply a "
        "placement order. Gravity is the only physics rule — you must place "
        "lower blocks before the blocks resting on them."
    )
    return "\n".join(lines)


def _describe_structure_geometric(structure: Structure) -> str:
    """Richer description: ground / top / per-block supports made explicit.

    This tests the hypothesis that most of what a text-only LLM needs for
    assembly planning is already baked into the prior — once you hand it the
    layout in verbal form, it one-shots the problem.
    """
    contacts: dict[int, list[int]] = {b.id: [] for b in structure.blocks}
    for c in structure.detect_contacts():
        if c.block_a in contacts and c.block_b in contacts:
            contacts[c.block_a].append(c.block_b)
            contacts[c.block_b].append(c.block_a)

    blocks = structure.blocks
    id_to_block = {b.id: b for b in blocks}
    ys = {b.id: b.vertices[:, 1].min() for b in blocks}
    y_tops = {b.id: b.vertices[:, 1].max() for b in blocks}
    xs_mid = {b.id: b.vertices[:, 0].mean() for b in blocks}

    on_ground = [b.id for b in blocks if abs(ys[b.id] - structure.ground_y) < 1e-6]

    # "B sits on A" means A's top is ≤ B's bottom (and they are neighbours).
    supports: dict[int, list[int]] = {b.id: [] for b in blocks}
    for b in blocks:
        for nb in set(contacts[b.id]):
            if y_tops[nb] <= ys[b.id] + 1e-6 and nb != b.id:
                supports[b.id].append(nb)

    on_top_of_nothing = [b.id for b in blocks
                         if not any(b.id in supports[o.id] for o in blocks)]

    lines = []
    lines.append(f"There are {len(blocks)} blocks and the ground plane at y={structure.ground_y}. "
                 "Gravity points down (−y). A block can only descend into its slot "
                 "straight from above.")
    lines.append(f"Blocks resting on the ground: {sorted(on_ground)}.")
    lines.append(f"Blocks with nothing on top of them (exposed upper surface): {sorted(on_top_of_nothing)}.")
    lines.append("")
    lines.append("Per-block geometry (sorted bottom-to-top, then left-to-right):")
    # Sort bottom-to-top, then left-to-right so the LLM gets a coherent reading order.
    ordered = sorted(blocks, key=lambda b: (ys[b.id], xs_mid[b.id]))
    for b in ordered:
        cx, cy = b.vertices.mean(axis=0)
        w = b.vertices[:, 0].max() - b.vertices[:, 0].min()
        h = y_tops[b.id] - ys[b.id]
        sup = sorted(supports[b.id]) or ["ground"]
        above = sorted([o.id for o in blocks if b.id in supports[o.id]])
        lines.append(
            f"  block {b.id}: centroid=({cx:+.2f},{cy:+.2f}) size={w:.2f}×{h:.2f}  "
            f"rests on {sup}; supports blocks above: {above if above else '(none)'}"
        )
    return "\n".join(lines)


def _run_verifier(
    structure: Structure,
    plan: list[int],
    block_ids: list[int],
    verifiers: list[Verifier],
) -> tuple[CEGISRound, str]:
    """Run the verifier chain on a proposed plan. Returns (round, feedback_text)."""
    n = len(block_ids)
    failure_step = None
    failed_block = None
    failed_verifier = None
    new_constraints = []
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
                        new_constraints.append(pc)
            break

    rnd = CEGISRound(
        round_num=-1, candidate=plan,
        failure_step=failure_step, failed_block=failed_block,
        failed_verifier=failed_verifier, new_constraints=new_constraints,
        steps=step_records,
    )

    if failure_step is None:
        return rnd, "ACCEPTED — every step passed the verifier chain."

    lines = [
        "REJECTED",
        f"  failed step: {failure_step}",
        f"  failing block: {failed_block}",
        f"  failing verifier: {failed_verifier}",
    ]
    for vr in step_records[-1].verifier_results:
        if not vr.feasible:
            lines.append(f"  reason: {vr.reason}")
    if new_constraints:
        lines.append("  learned precedence constraints:")
        for pc in new_constraints:
            lines.append(f"    - place block {pc.before} before block {pc.after}  ({pc.reason})")
    lines.append("Call submit_plan again with a plan that respects these constraints.")
    return rnd, "\n".join(lines)


def _validate_plan(plan_arg, block_ids: list[int]) -> tuple[list[int] | None, str | None]:
    if not isinstance(plan_arg, list) or not all(isinstance(x, int) for x in plan_arg):
        return None, "argument `plan` must be a list of integers."
    if sorted(plan_arg) != sorted(block_ids):
        return None, f"plan must be a permutation of {block_ids}, got {plan_arg}."
    return plan_arg, None


def solve_llm(
    structure: Structure,
    max_rounds: int = 30,
    friction: float = 0.7,
    verifiers: list[Verifier] | None = None,
    model: str = LLM_MODEL,
    verbose: bool = False,
    image_content: list | None = None,
    description_mode: str = "basic",
    permute_ids: bool = False,
    permute_seed: int = 1234,
) -> tuple[CEGISResult, list[LLMCallTrace]]:
    """CEGIS with an LLM proposer that calls `submit_plan` each turn.

    image_content: optional OpenAI-format content blocks (type: image_url) to
    prepend to the initial user message — this lets the VLM solver reuse the
    same loop and only replace the first-turn description with a picture.
    """
    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY not set")

    real_block_ids = [b.id for b in structure.blocks]
    n = len(real_block_ids)
    if verifiers is None:
        verifiers = default_chain(friction=friction)

    # Optionally show the LLM permuted block ids so the natural labelling
    # doesn't leak the placement order. Bijection: display_id ↔ real_id.
    if permute_ids:
        import copy
        import random as _r
        perm = list(real_block_ids)
        _r.Random(permute_seed).shuffle(perm)
        # display_id[i] is the label shown to the LLM for real block i
        display_of_real = {real: perm[idx] for idx, real in enumerate(real_block_ids)}
        real_of_display = {d: r for r, d in display_of_real.items()}
        # Build a shadow structure whose block.id fields use display labels.
        shadow = copy.deepcopy(structure)
        for b in shadow.blocks:
            b.id = display_of_real[b.id]
        describe_structure = shadow
        block_ids = [display_of_real[r] for r in real_block_ids]
    else:
        describe_structure = structure
        block_ids = list(real_block_ids)
        real_of_display = {i: i for i in real_block_ids}

    # Initial user turn: describe the task.
    if image_content is not None:
        desc = ""  # VLM: the image carries the spatial info.
    elif description_mode == "geometric":
        desc = _describe_structure_geometric(describe_structure) + "\n\n"
    else:
        desc = _describe_structure_basic(describe_structure) + "\n\n"
    intro = (
        f"There are {n} blocks with ids {block_ids}. Your job is to find a "
        f"placement order that passes the verifier.\n\n"
        f"{desc}"
        f"Call submit_plan with a permutation of all {n} ids."
    )
    if image_content:
        user_content = image_content + [{"type": "text", "text": intro}]
    else:
        user_content = intro

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    rounds: list[CEGISRound] = []
    trace: list[LLMCallTrace] = []
    total_pruned = 0

    for round_num in range(max_rounds):
        # Fireworks caps non-streaming completions at 4096 tokens. That is
        # tight for reasoning-tuned models like kimi, which can spend most
        # of it on internal thought before emitting the tool call — hence
        # the occasional "no tool call" round in the trace.
        payload = {
            "model": model,
            "max_tokens": 4096,
            "messages": messages,
            "tools": [SUBMIT_PLAN_TOOL],
            "tool_choice": {"type": "function", "function": {"name": "submit_plan"}},
        }
        resp = requests.post(
            FIREWORKS_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        raw_id = data.get("id")

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # Treat as a wasted round.
            rounds.append(CEGISRound(
                round_num=round_num, candidate=[], failure_step=None,
                failed_block=None, failed_verifier="no_tool_call",
                new_constraints=[], steps=[],
            ))
            trace.append(LLMCallTrace(round_num, None, "(no tool call)", raw_id))
            # Nudge model to use tool.
            messages.append({"role": "assistant", "content": msg.get("content") or ""})
            messages.append({
                "role": "user",
                "content": "You must call the submit_plan tool. Try again.",
            })
            continue

        tc = tool_calls[0]
        tc_id = tc["id"]
        try:
            args = json.loads(tc["function"]["arguments"])
            plan_arg = args.get("plan")
        except Exception as e:
            plan_arg = None
            parse_err = str(e)
        else:
            parse_err = None

        plan_display, err = (None, parse_err) if plan_arg is None else _validate_plan(plan_arg, block_ids)
        # Translate display ids back to real ids for the verifier.
        plan = ([real_of_display[d] for d in plan_display]
                if plan_display is not None else None)

        # Always echo the assistant turn (tool call) back into history —
        # OpenAI-style protocols require the tool response to follow it.
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": [tc],
        })

        if plan is None:
            fb = f"REJECTED — {err}. Call submit_plan again with a valid permutation."
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": fb})
            rounds.append(CEGISRound(
                round_num=round_num, candidate=[], failure_step=None,
                failed_block=None, failed_verifier=f"bad_args:{err}",
                new_constraints=[], steps=[],
            ))
            trace.append(LLMCallTrace(round_num, None, fb, raw_id))
            continue

        # Run verifier on the shadow (display-id) structure so all feedback
        # naturally refers to display ids the LLM recognises.
        rnd, feedback = _run_verifier(describe_structure, plan_display,
                                      block_ids, verifiers)
        rnd.round_num = round_num
        rnd.pruned_count = _estimate_pruned(n, len(rnd.new_constraints))
        total_pruned += rnd.pruned_count
        rounds.append(rnd)

        messages.append({"role": "tool", "tool_call_id": tc_id, "content": feedback})
        trace.append(LLMCallTrace(round_num, plan, feedback, raw_id))

        if verbose:
            print(f"\n[round {round_num}] plan={plan}\n{feedback}")

        if rnd.failure_step is None:
            return CEGISResult(
                feasible=True, sequence=plan, rounds=rounds,
                constraints=[pc for r2 in rounds for pc in r2.new_constraints],
                total_pruned=total_pruned,
            ), trace

    return CEGISResult(
        feasible=False, sequence=None, rounds=rounds,
        constraints=[pc for r in rounds for pc in r.new_constraints],
        total_pruned=total_pruned,
    ), trace
