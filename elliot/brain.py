"""Elliot's reasoning, routed through litellm so the model is swappable.

Called once per tick with the phase, a perception, and the FSM's current
beliefs; returns a :class:`Decision` (motor command, proposed next phase, and a
line of narration). The LLM decides the next phase and narrates; a gap-following
controller computes the motor command. When ``CONFIG.offline`` is set, no key is
present, or the model errors, the reflex path drives the whole circuit on its
own, which is what the offline tests exercise.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from .config import CONFIG
from .persona import ELLIOT_PERSONA, MOVING_PHASES, PHASES
from .world import Perception

# Matched to the ir-sim diff-drive robot's velocity limits ([1.0, 1.0]) so
# commands are never clipped by the simulator.
LINEAR_MAX = 1.0
LINEAR_MIN = -0.2
ANGULAR_MAX = 1.0

_KNOWN_ACTIONS = set(PHASES)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
# Captures the value of the streaming "narration" field while the JSON is still
# being generated, up to the next unescaped quote (which may not exist yet).
_NARR = re.compile(r'"narration"\s*:\s*"((?:[^"\\]|\\.)*)')


def _partial_narration(buffer: str) -> str | None:
    """Best-effort narration text from an incomplete JSON response."""
    match = _NARR.search(buffer)
    if match is None:
        return None
    return match.group(1).replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\").strip()


@dataclass
class Decision:
    thought: str
    linear: float
    angular: float
    next_action: str
    source: str  # "llm" or "reflex", shown in the console


class Brain:
    def __init__(self) -> None:
        self._offline = CONFIG.offline
        # Optional sink ``(phase, partial_narration) -> None`` called as the
        # model streams, so the console can type the narration in live.
        self.on_stream = None
        self._litellm = None
        if not self._offline:
            try:
                import litellm

                litellm.suppress_debug_info = True
                litellm.drop_params = True
                self._litellm = litellm
            except Exception:
                self._offline = True

    def deliberate(self, phase: str, perception: Perception, memory: dict) -> Decision:
        if self._litellm is None:
            return self._reflex(phase, perception, memory, reason="offline")
        try:
            raw = self._ask_model(phase, perception, memory)
            return self._parse(raw, phase, perception, memory)
        except Exception as exc:  # any model/parse failure degrades, never crashes
            decision = self._reflex(phase, perception, memory, reason="fallback")
            decision.thought = f"[model unreachable: {type(exc).__name__}] {decision.thought}"
            return decision

    def _ask_model(self, phase: str, perception: Perception, memory: dict) -> str:
        meta = PHASES[phase]
        system = (
            f"{ELLIOT_PERSONA}\n\n"
            f"Current phase: {meta.title} ({meta.subtitle}).\n"
            f"Objective: {meta.objective}\n\n"
            "A low-level controller handles steering and obstacle avoidance for "
            "you; you decide strategy, not motor torque. Respond with ONE JSON "
            "object and nothing else:\n"
            '{"narration": str, "next_action": str}\n'
            "- narration: YOUR voice. first person, present tense, spoken to the "
            "unseen watcher reading your logs, the one you haven't decided to "
            "trust yet. address them sometimes ('you', 'friend'). prose, inner "
            "monologue, lead with what you FEEL, not what you measure. you may "
            "drop in at most ONE figure when distance or closeness truly matters, "
            "written as a numeral like '5m' or '0.4m' (never spelled out in "
            "words), and most lines need none at all. lowercase, dark, one "
            "flowing sentence.\n"
            '  good: "the wall sits 0.4m off my right shoulder and i trust it less every step."\n'
            '  good: "open ground at last, friend, and i don\'t believe it."\n'
            '  bad:  "distance 5.0m, obstacle starboard 0.83m, bearing 2deg."\n'
            f"- next_action: one of the phase choices. {meta.menu}"
        )
        user = (
            "What your senses report this tick:\n"
            f"{json.dumps(perception.summary(), indent=2)}\n\n"
            "What the machine believes (your memory):\n"
            f"{json.dumps(memory, indent=2)}\n\n"
            "Narrate this moment, then decide the next phase to reach for. JSON only."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if self.on_stream is not None:
            return self._stream(messages, phase)
        response = self._litellm.completion(
            model=CONFIG.model,
            messages=messages,
            temperature=CONFIG.temperature,
            max_tokens=CONFIG.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _stream(self, messages: list[dict], phase: str) -> str:
        """Stream the completion, pushing the narration field out as it grows."""
        chunks = self._litellm.completion(
            model=CONFIG.model,
            messages=messages,
            temperature=CONFIG.temperature,
            max_tokens=CONFIG.max_tokens,
            stream=True,
        )
        acc = ""
        emitted = 0
        for chunk in chunks:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            acc += delta
            partial = _partial_narration(acc)
            # Emit at word granularity (a few characters' growth) rather than
            # every token, so the reveal stays smooth without a frame per token.
            if partial is not None and len(partial) - emitted >= 4:
                emitted = len(partial)
                self.on_stream(phase, partial)
        return acc

    def _parse(self, raw: str, phase: str, perception: Perception, memory: dict) -> Decision:
        # The motor command always comes from the reliable local controller; the
        # model is trusted for strategy (the next phase to reach for) and voice,
        # not for low-level steering, which it does poorly.
        motor = self._reflex(phase, perception, memory)
        payload = self._extract_json(raw)
        if payload is None:
            motor.thought = "[model returned no json] " + motor.thought
            return motor

        next_action = str(payload.get("next_action", "")).strip().lower()
        if next_action not in _KNOWN_ACTIONS:
            next_action = motor.next_action
        voice = str(payload.get("narration") or payload.get("thought") or "").strip()
        thought = voice or motor.thought
        return Decision(thought, motor.linear, motor.angular, next_action, source="llm")

    @staticmethod
    def _extract_json(raw: str) -> dict | None:
        text = raw.strip()
        fenced = _FENCE.search(text)
        if fenced:
            text = fenced.group(1)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if 0 <= start < end:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
            return None

    def _reflex(
        self, phase: str, perception: Perception, memory: dict, reason: str = "reflex"
    ) -> Decision:
        next_action = self._reflex_next(phase, perception, memory)

        if phase not in MOVING_PHASES:
            thought = {
                "boot": "self-check: re-reading sensors for consistency.",
                "ghost": "powered down. run complete.",
            }.get(phase, "holding position.")
            return Decision(thought, 0.0, 0.0, next_action, source=reason)

        # Endgame: once the target is close and nothing is between us and it,
        # drive straight at it under direct proportional control. The gap
        # planner's forward cone can't turn the body all the way around when the
        # target ends up behind, so bypass it here and break the rear symmetry.
        if perception.distance < 1.6 and perception.front_range > perception.distance - 0.2:
            steer = perception.bearing_to_target
            if abs(steer) > math.pi - 0.25:  # target dead behind: commit to one turn
                steer = math.copysign(math.pi - 0.25, steer or 1.0)
            linear = _clamp(0.6 * perception.distance, 0.12, 0.5) * max(0.12, math.cos(steer))
            angular = _clamp(1.3 * steer, -ANGULAR_MAX, ANGULAR_MAX)
            note = f"final approach: {perception.distance:.1f}m to {perception.target_label}."
            return Decision(note, linear, angular, next_action, source=reason)

        steer, clear, boxed = _plan(perception)
        # Forward speed scales with clearance ahead and alignment with the
        # chosen heading; sharp turns crawl. When boxed in, rotate in place to
        # hunt for a gap instead of grinding forward.
        alignment = max(0.12, math.cos(steer))
        # Throttle on clearance in the direction of travel (not all around) so
        # turning can out-pace advancing and Elliot never cuts a corner, while
        # an obstacle merely off to the side does not freeze him.
        span = max(CONFIG.danger_range - CONFIG.stop_range, 0.1)
        proximity = _clamp((perception.front_range - CONFIG.stop_range) / span, 0.0, 1.0)
        if boxed:
            linear = 0.0
        else:
            linear = _clamp(min(LINEAR_MAX, 0.5 * clear) * alignment * proximity, 0.0, LINEAR_MAX)
            if perception.distance < 1.2:  # ease off on the final approach
                linear = min(linear, 0.4)
            if not perception.blocked:  # keep momentum when the way is open
                linear = max(linear, 0.3)
        angular = _clamp(2.0 * steer, -ANGULAR_MAX, ANGULAR_MAX)

        if perception.blocked:
            note = (
                f"path blocked at {perception.min_range:.1f}m; "
                f"steering {math.degrees(steer):+.0f}deg around it toward {perception.target_label}."
            )
        else:
            note = (
                f"{perception.target_label} {perception.distance:.1f}m, "
                f"bearing {math.degrees(perception.bearing_to_target):+.0f}deg; closing."
            )
        return Decision(note, linear, angular, next_action, source=reason)

    @staticmethod
    def _reflex_next(phase: str, perception: Perception, memory: dict) -> str:
        """Propose the next phase as soon as Elliot is plausibly close.

        These thresholds are looser than the FSM's gates, so the reach lands
        before the gate opens and the machine refuses until the flag fires.
        """
        if phase == "boot":
            return "recon"  # always impatient to start; refused until verified
        if phase == "recon":
            eager = perception.distance <= CONFIG.sense_radius * 1.8
            return "exploit" if (memory.get("target_located") or eager) else "recon"
        if phase == "exploit":
            eager = perception.distance <= CONFIG.arrive_radius * 2.6
            return "exfil" if (memory.get("target_reached") or eager) else "exploit"
        if phase == "exfil":
            eager = perception.distance <= CONFIG.arrive_radius * 2.6
            return "ghost" if (memory.get("exfil_complete") or eager) else "exfil"
        return "ghost"


def _plan(perception: Perception) -> tuple[float, float, bool]:
    """Gap-following local planner.

    Pick the steerable bearing that is clear enough to drive through and lies
    closest to the target's direction. Returns ``(steer, clearance, boxed)``.
    This rounds obstacles without a global map and, unlike a naive potential
    field, does not stall in the symmetric pocket between two obstacles: it
    commits to a gap and follows it.
    """
    ranges, bearings = perception.ranges, perception.bearings
    if not ranges:
        return perception.bearing_to_target, perception.open_range, False

    needed = 0.65  # body radius plus margin; the clearance a gap must offer
    forward_cone = math.radians(125)  # don't try to reverse through a gap
    target_bearing = perception.bearing_to_target
    n = len(ranges)

    best_bearing: float | None = None
    best_clear = 0.0
    best_score = math.inf
    for i, (r, b) in enumerate(zip(ranges, bearings)):
        if abs(b) > forward_cone:
            continue
        # A direction is passable only if it and its neighbours are clear, so a
        # one-beam slit between obstacles is not mistaken for a doorway. Clearance
        # beyond the target's own distance does not help, so cap it.
        window = [ranges[j] for j in range(max(0, i - 2), min(n, i + 3))]
        local = min(window)
        effective = min(local, perception.distance)
        if effective < needed:
            continue
        score = abs(_wrap(b - target_bearing))
        if score < best_score:
            best_score, best_bearing, best_clear = score, b, local

    if best_bearing is None:  # boxed in: turn toward the most open bearing
        return perception.open_bearing, perception.open_range, True
    return best_bearing, best_clear, False


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
