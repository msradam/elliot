"""the world and my senses. a headless ir-sim wrapper.

builds the sim with the plotting off and hands out only what the machine and the
console need, through :meth:`World.perceive`. the readings the gates care about
(``arrive``, ``collision``) come straight from ir-sim, so the machine checks
facts, not anything i have only talked myself into believing.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np

# no display. ir-sim drags in matplotlib, so force Agg before anything imports
# it. nobody watches this run but the console i draw myself.
os.environ.setdefault("MPLBACKEND", "Agg")

from .config import CONFIG


@dataclass
class Perception:
    """one look at the world, the way my senses report it this tick."""

    tick: int
    pose: tuple[float, float, float]  # x, y, heading (radians)
    target: tuple[float, float]  # current objective in world coords
    target_label: str  # "target" during the approach, "exfil point" on the way out
    distance: float  # metres to the current target
    bearing_to_target: float  # radians, relative to heading (left +, right -)
    ranges: list[float]  # lidar beam lengths
    bearings: list[float]  # lidar beam angles relative to heading
    min_range: float  # closest obstacle in any direction
    front_range: float  # closest obstacle within the forward cone (direction of travel)
    open_bearing: float  # heading-relative angle of the most open beam
    open_range: float  # length of that most open beam
    collision: bool  # ir-sim says we are touching something
    arrived: bool  # ir-sim says we are at the goal
    width: float
    height: float

    @property
    def blocked(self) -> bool:
        return self.min_range < CONFIG.danger_range

    def summary(self) -> dict[str, object]:
        """a compact, json-friendly read for the model's prompt and the ledger."""
        return {
            "tick": self.tick,
            "position": [round(self.pose[0], 2), round(self.pose[1], 2)],
            "heading_deg": round(math.degrees(self.pose[2]) % 360, 1),
            "target": self.target_label,
            "target_position": [round(self.target[0], 2), round(self.target[1], 2)],
            "distance_to_target_m": round(self.distance, 2),
            "bearing_to_target_deg": round(math.degrees(self.bearing_to_target), 1),
            "nearest_obstacle_m": round(self.min_range, 2),
            "obstacle_ahead_m": round(self.front_range, 2),
            "path_blocked": self.blocked,
            "most_open_bearing_deg": round(math.degrees(self.open_bearing), 1),
            "most_open_range_m": round(self.open_range, 2),
            "collision": self.collision,
            "arrival_flag": self.arrived,
        }


class World:
    """one robot in a 2d ir-sim world, driven headless."""

    def __init__(self, world_path: str | None = None) -> None:
        import irsim

        path = str(world_path or CONFIG.world_path)
        self._env = irsim.make(path, display=False, disable_all_plot=True)
        self._robot = self._env.robot_list[0]
        self._tick = 0

        start = np.asarray(self._robot.state).flatten()
        self._origin = (float(start[0]), float(start[1]))
        goal = np.asarray(self._robot.goal).flatten()
        self._goal = (float(goal[0]), float(goal[1]))

        # until i reach the target the objective is the goal. after that it
        # flips to the exfil point, which is wherever i booted.
        self._exfil = False
        self._trail: list[tuple[float, float]] = [self._origin]

    def begin_exfil(self) -> None:
        """i have it. flip the objective from the target to the exfil point."""
        self._exfil = True

    @property
    def exfil_active(self) -> bool:
        return self._exfil

    def _active_target(self) -> tuple[tuple[float, float], str]:
        if self._exfil:
            return self._origin, "exfil point"
        return self._goal, "target"

    def perceive(self) -> Perception:
        state = np.asarray(self._robot.state).flatten()
        x, y, theta = float(state[0]), float(state[1]), float(state[2])

        scan = self._env.get_lidar_scan(0)
        ranges = [float(r) for r in np.asarray(scan["ranges"]).flatten()]
        amin, amax = float(scan["angle_min"]), float(scan["angle_max"])
        bearings = list(np.linspace(amin, amax, len(ranges))) if ranges else []
        if ranges:
            min_idx = int(np.argmin(ranges))
            max_idx = int(np.argmax(ranges))
            min_range = ranges[min_idx]
            open_bearing = float(bearings[max_idx])
            open_range = ranges[max_idx]
            front = [r for r, b in zip(ranges, bearings) if abs(b) < 0.61]  # +/-35deg
            front_range = min(front) if front else min_range
        else:
            min_range, front_range, open_bearing, open_range = math.inf, math.inf, 0.0, 0.0

        target, label = self._active_target()
        dx, dy = target[0] - x, target[1] - y
        distance = math.hypot(dx, dy)
        bearing = _wrap(math.atan2(dy, dx) - theta)

        return Perception(
            tick=self._tick,
            pose=(x, y, theta),
            target=target,
            target_label=label,
            distance=distance,
            bearing_to_target=bearing,
            ranges=ranges,
            bearings=[float(b) for b in bearings],
            min_range=min_range,
            front_range=front_range,
            open_bearing=open_bearing,
            open_range=open_range,
            collision=bool(self._robot.collision),
            arrived=self._target_arrived(distance),
            width=float(self._env._world.width),
            height=float(self._env._world.height),
        )

    def _target_arrived(self, distance: float) -> bool:
        """ground-truth arrival at whichever objective is active.

        for the target i trust ir-sim's own ``arrive`` flag, nothing of mine.
        the exfil point is just a coordinate ir-sim does not track as a goal, so
        there i fall back to distance.
        """
        if self._exfil:
            return distance <= CONFIG.arrive_radius
        return bool(self._robot.arrive) or distance <= CONFIG.arrive_radius

    def drive(self, linear: float, angular: float) -> None:
        self._env.step(np.array([[float(linear)], [float(angular)]]))
        self._tick += 1
        self._record_trail()

    def hold(self) -> None:
        """let time pass without moving. the senses still refresh."""
        self._env.step(np.array([[0.0], [0.0]]))
        self._tick += 1
        self._record_trail()

    def _record_trail(self) -> None:
        state = np.asarray(self._robot.state).flatten()
        self._trail.append((float(state[0]), float(state[1])))

    @property
    def trail(self) -> list[tuple[float, float]]:
        return list(self._trail)

    @property
    def width(self) -> float:
        return float(self._env._world.width)

    @property
    def height(self) -> float:
        return float(self._env._world.height)

    @property
    def origin(self) -> tuple[float, float]:
        return self._origin

    @property
    def goal(self) -> tuple[float, float]:
        return self._goal

    def obstacles(self) -> list[tuple[float, float, float]]:
        out: list[tuple[float, float, float]] = []
        for info in self._env.get_obstacle_info_list():
            center = np.asarray(info.center).flatten()
            radius = float(getattr(info, "radius", 0.3) or 0.3)
            out.append((float(center[0]), float(center[1]), radius))
        return out


def _wrap(angle: float) -> float:
    """wrap an angle to (-pi, pi]."""
    return (angle + math.pi) % (2 * math.pi) - math.pi
