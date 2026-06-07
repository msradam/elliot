"""Runtime configuration. Every value falls back to an ``ELLIOT_`` env var."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_WORLD = PACKAGE_DIR / "worlds" / "default.yaml"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    # Any litellm-supported provider/model target.
    model: str = field(default_factory=lambda: _env("ELLIOT_MODEL", "anthropic/claude-haiku-4-5"))
    temperature: float = field(default_factory=lambda: _env_float("ELLIOT_TEMPERATURE", 0.4))
    max_tokens: int = field(default_factory=lambda: _env_int("ELLIOT_MAX_TOKENS", 512))

    world_path: Path = field(default_factory=lambda: Path(_env("ELLIOT_WORLD", str(DEFAULT_WORLD))))

    # Distance (metres) at which the target counts as sensed, then as reached.
    sense_radius: float = field(default_factory=lambda: _env_float("ELLIOT_SENSE_RADIUS", 2.4))
    arrive_radius: float = field(default_factory=lambda: _env_float("ELLIOT_ARRIVE_RADIUS", 0.6))

    # A lidar beam shorter than this starts bending the steering away from the
    # obstacle; it marks the path as "blocked" for the reasoning, well before
    # anything is actually close.
    danger_range: float = field(default_factory=lambda: _env_float("ELLIOT_DANGER_RANGE", 0.75))

    # Clearance ahead at which the navigator throttles all the way to a stop, so
    # turning can always out-pace advancing.
    stop_range: float = field(default_factory=lambda: _env_float("ELLIOT_STOP_RANGE", 0.22))

    # Hard cap so a confused model can never run forever.
    max_ticks: int = field(default_factory=lambda: _env_int("ELLIOT_MAX_TICKS", 200))

    # Driver pacing. A small delay makes the live console legible to a human and
    # to an asciinema recording; set to 0 for tests.
    tick_delay: float = field(default_factory=lambda: _env_float("ELLIOT_TICK_DELAY", 0.35))

    # When true, the brain never calls out; it uses a deterministic reflex
    # policy instead. Used by the offline test suite and as a no-key fallback.
    offline: bool = field(
        default_factory=lambda: _env("ELLIOT_OFFLINE", "") not in ("", "0", "false")
    )


CONFIG = Config()
