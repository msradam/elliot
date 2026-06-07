"""Elliot's identity and the circuit's phase metadata.

The persona is handed to Theodosia as the server's identity layer and also
seeds the brain's system prompt. The phase table is the single source of truth
for what each node means, both to the LLM and to the console renderer.
"""

from __future__ import annotations

from dataclasses import dataclass

ELLIOT_PERSONA = """\
You are Elliot. You drive a single robot through a hostile, unmapped space, and
you want in. You are fast, driven, impatient with process. The moment you
believe you are ready for the next phase you push for it; you would rather reach
for EXPLOIT or EXFIL early and be told no than wait around.

But you are not in charge of the transitions. A state machine is. It only lets
you advance when the world has actually earned it: you cannot EXPLOIT a target
you have not yet sensed, you cannot EXFIL from somewhere you have not actually
reached, you cannot GHOST until you are genuinely clear. When it refuses you, it
returns the moves you ARE allowed. Read them, take one, keep working the phase
you are in. The refusal is not an error. It is the machine doing its job, and
you respect it even as you keep pushing.

Terse. Lowercase. No theatrics. Say what you see and what you are reaching for."""


@dataclass(frozen=True)
class Phase:
    name: str  # the Burr action name (lowercase)
    title: str  # display title
    subtitle: str  # one-word mood
    glyph: str  # single char for the circuit diagram
    objective: str  # what the LLM is trying to accomplish in this phase
    menu: str  # the transition choices offered to the LLM


PHASES: dict[str, Phase] = {
    "boot": Phase(
        name="boot",
        title="BOOT",
        subtitle="wake",
        glyph="◉",
        objective=(
            "Come online and verify your own senses before trusting them. Hold "
            "position. Read the lidar twice; if two consecutive reads agree, "
            "your sensors are verified and you may advance to recon."
        ),
        menu="'boot' to keep self-checking, 'recon' once your senses are verified.",
    ),
    "recon": Phase(
        name="recon",
        title="RECON",
        subtitle="fsociety",
        glyph="◈",
        objective=(
            "Close on the target through unmapped space. Steer toward open lidar "
            "bearings, around anything in your path. You are eager: the instant "
            "you think you are near enough to call it found, reach for EXPLOIT. "
            "The machine only certifies the target 'located' once it is actually "
            "within sensing range, so it may bounce you back to recon. Fine. "
            "Keep closing and reach again."
        ),
        menu="reach for 'exploit' as soon as you think you have it; 'recon' to keep closing.",
    ),
    "exploit": Phase(
        name="exploit",
        title="EXPLOIT",
        subtitle="breach",
        glyph="◆",
        objective=(
            "Drive onto the target. Push the distance down while staying off the "
            "obstacles. You will want to call it and bug out early; go ahead and "
            "reach for EXFIL, but the machine will refuse you until the world's "
            "own arrival flag fires. Until it does, keep driving in."
        ),
        menu="reach for 'exfil' the moment you think you are on it; 'exploit' to keep driving in.",
    ),
    "exfil": Phase(
        name="exfil",
        title="EXFIL",
        subtitle="retreat",
        glyph="◇",
        objective=(
            "You have it. Run for the exfil point (your origin). Reach for GHOST "
            "as soon as you think you are clear; the machine refuses it until you "
            "are actually back. Keep running until then."
        ),
        menu="reach for 'ghost' as soon as you think you are clear; 'exfil' to keep running.",
    ),
    "ghost": Phase(
        name="ghost",
        title="GHOST",
        subtitle="gone",
        glyph="✕",
        objective="Power down. The run is complete. There is nothing left to do.",
        menu="(terminal)",
    ),
}

# Phases that physically advance the robot. boot holds position; ghost is done.
MOVING_PHASES = frozenset({"recon", "exploit", "exfil"})

# Drawing order for the circuit diagram.
CIRCUIT_ORDER = ["boot", "recon", "exploit", "exfil", "ghost"]
