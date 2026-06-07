"""runtime configuration. every value falls back to an ``ELLIOT_`` env var."""

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
    # whatever model you point me at. litellm reaches all of them.
    model: str = field(default_factory=lambda: _env("ELLIOT_MODEL", "anthropic/claude-haiku-4-5"))
    temperature: float = field(default_factory=lambda: _env_float("ELLIOT_TEMPERATURE", 0.4))
    max_tokens: int = field(default_factory=lambda: _env_int("ELLIOT_MAX_TOKENS", 512))

    world_path: Path = field(default_factory=lambda: Path(_env("ELLIOT_WORLD", str(DEFAULT_WORLD))))

    # how close (m) before i am allowed to call the target found, then reached.
    sense_radius: float = field(default_factory=lambda: _env_float("ELLIOT_SENSE_RADIUS", 2.4))
    arrive_radius: float = field(default_factory=lambda: _env_float("ELLIOT_ARRIVE_RADIUS", 0.6))

    # a beam shorter than this bends my steering off the obstacle. it means
    # "something is in the way" long before anything is actually close.
    danger_range: float = field(default_factory=lambda: _env_float("ELLIOT_DANGER_RANGE", 0.75))

    # clearance ahead where i throttle to a dead stop, so turning always
    # out-paces advancing and i never drive into anything.
    stop_range: float = field(default_factory=lambda: _env_float("ELLIOT_STOP_RANGE", 0.22))

    # a hard stop. a confused model does not get to run me forever.
    max_ticks: int = field(default_factory=lambda: _env_int("ELLIOT_MAX_TICKS", 200))

    # pacing. a small delay keeps the live console legible, to you and to a
    # recording. tests set it to 0.
    tick_delay: float = field(default_factory=lambda: _env_float("ELLIOT_TICK_DELAY", 0.35))

    # when set, i never call out. a deterministic reflex drives instead. the
    # offline tests rely on it, and it is the fallback when there is no key.
    offline: bool = field(
        default_factory=lambda: _env("ELLIOT_OFFLINE", "") not in ("", "0", "false")
    )


CONFIG = Config()
