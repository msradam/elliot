"""the circuit: a burr application, mounted as an mcp server by theodosia.

the phases are burr actions, the edges are conditional transitions. theodosia
only offers a transition whose condition holds against the live state, so every
gate is a fact the world has to supply, not a claim i can make:

  BOOT -> RECON -> EXPLOIT -> EXFIL -> GHOST

  boot->recon     sensors_verified  (two consecutive sensor reads agree)
  recon->exploit  target_located    (target within sensing range)
  exploit->exfil  target_reached    (ir-sim's own arrival flag)
  exfil->ghost    exfil_complete    (back at the exfil point)
"""

from __future__ import annotations

import math
from typing import Any

from burr.core import Application, ApplicationBuilder, State, action, when

from .brain import Brain
from .config import CONFIG
from .persona import ELLIOT_PERSONA, MOVING_PHASES
from .world import World

STATE_KEYS = [
    "tick",
    "phase",
    "sensors_verified",
    "target_located",
    "target_reached",
    "exfil_complete",
    "proposed_next",
    "thought",
    "source",
    "prev_min_range",
    "perception",
]

ACTION_NAMES = ["boot", "recon", "exploit", "exfil", "ghost"]


def initial_state() -> dict[str, Any]:
    return {
        "tick": 0,
        "phase": "boot",
        "sensors_verified": False,
        "target_located": False,
        "target_reached": False,
        "exfil_complete": False,
        "proposed_next": "boot",
        "thought": "cold boot. trusting nothing yet.",
        "source": "init",
        "prev_min_range": None,
        "perception": {},
    }


def _memory(state: State, phase: str) -> dict[str, Any]:
    """what the machine believes right now, handed to me to reason over."""
    return {
        "phase": phase,
        "sensors_verified": state["sensors_verified"],
        "target_located": state["target_located"],
        "target_reached": state["target_reached"],
        "exfil_complete": state["exfil_complete"],
        "last_thought": state["thought"],
    }


def _advance(world: World, brain: Brain, state: State, phase: str) -> tuple[dict, State]:
    """run one phase: read the senses, think, act, set the honest gate flags."""
    before = world.perceive()
    decision = brain.deliberate(phase, before, _memory(state, phase))

    if phase in MOVING_PHASES:
        world.drive(decision.linear, decision.angular)
    else:  # boot and ghost hold position
        world.hold()
    after = world.perceive()

    # carry the latched gate flags forward. each phase only flips its own.
    flags = {
        "sensors_verified": state["sensors_verified"],
        "target_located": state["target_located"],
        "target_reached": state["target_reached"],
        "exfil_complete": state["exfil_complete"],
    }

    if phase == "boot":
        prev = state["prev_min_range"]
        consistent = (
            prev is not None
            and math.isfinite(after.min_range)
            and abs(after.min_range - prev) <= 0.6
            and not after.collision
        )
        if consistent:
            flags["sensors_verified"] = True

    elif phase == "recon":
        if after.distance <= CONFIG.sense_radius:
            flags["target_located"] = True

    elif phase == "exploit":
        if after.arrived:
            flags["target_reached"] = True
            world.begin_exfil()

    elif phase == "exfil":
        if after.arrived:
            flags["exfil_complete"] = True

    result = {
        "phase": phase,
        "thought": decision.thought,
        "proposed_next": decision.next_action,
        "source": decision.source,
    }
    new_state = state.update(
        tick=after.tick,
        phase=phase,
        proposed_next=decision.next_action,
        thought=decision.thought,
        source=decision.source,
        prev_min_range=after.min_range if math.isfinite(after.min_range) else None,
        perception=after.summary(),
        **flags,
    )
    return result, new_state


def _make_actions(world: World, brain: Brain) -> dict[str, Any]:
    actions: dict[str, Any] = {}
    for phase in ACTION_NAMES:

        def _fn(state: State, _phase: str = phase) -> tuple[dict, State]:
            return _advance(world, brain, state, _phase)

        _fn.__name__ = phase
        actions[phase] = action(reads=STATE_KEYS, writes=STATE_KEYS)(_fn)
    return actions


# a bare (from, to) tuple is an always-open edge. a third element is the
# condition the world has to satisfy before the machine will even offer it.
_TRANSITIONS = [
    ("boot", "recon", when(sensors_verified=True)),
    ("boot", "boot", when(sensors_verified=False)),
    ("recon", "exploit", when(target_located=True)),
    ("recon", "recon"),
    ("exploit", "exfil", when(target_reached=True)),
    ("exploit", "exploit"),
    ("exfil", "ghost", when(exfil_complete=True)),
    ("exfil", "exfil", when(exfil_complete=False)),
    # ghost is terminal: no outgoing transitions.
]


def build_application(world: World, brain: Brain, *, with_tracker: bool = True) -> Application:
    """assemble the burr application that is my control circuit."""
    actions = _make_actions(world, brain)
    builder = (
        ApplicationBuilder()
        .with_actions(**actions)
        .with_transitions(*_TRANSITIONS)
        .with_entrypoint("boot")
        .with_state(**initial_state())
    )
    if with_tracker:
        try:
            import theodosia

            builder = builder.with_tracker(theodosia.tracker("elliot"))
        except Exception:
            pass
    return builder.build()


def _next_hint(state, valid_next_actions, last_action, refusal=None) -> str | None:
    """one line of guidance stapled to every step response."""
    if refusal is not None:
        return "the machine refused that. you have not earned it yet. read valid_next_actions."
    if not valid_next_actions:
        return "circuit complete. you are a ghost."
    return None


def mount_server(world: World, brain: Brain):
    """mount the circuit as a theodosia mcp server (shared-app, single client)."""
    import theodosia

    app = build_application(world, brain)
    return theodosia.mount(
        app,
        name="elliot",
        instructions=(
            "You are driving Elliot, an eager robot, through a 2D world. Each "
            "step runs one phase of his circuit. Reach for the next phase when "
            "you think you are ready; honor refusals when you are not."
        ),
        personas={"elliot": ELLIOT_PERSONA},
        default_persona="elliot",
        next_hint=_next_hint,
    )
