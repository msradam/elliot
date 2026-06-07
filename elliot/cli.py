"""the command line: ``elliot`` (or ``python run.py``).

flags become the ``ELLIOT_*`` env vars that :mod:`elliot.config` reads, then the
driver runs. online needs an api key in the environment; envchain is the clean
way (``envchain ai elliot``). with no key i fall back to the offline reflex so
the loop still finishes.
"""

from __future__ import annotations

import argparse
import os
import sys

_API_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "TOGETHER_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
)


def _has_api_key() -> bool:
    return any(os.environ.get(v) for v in _API_KEY_VARS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="elliot",
        description="An LLM-driven state machine in control of a paranoid robot.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline", action="store_true", help="use the deterministic reflex navigator, no LLM"
    )
    mode.add_argument(
        "--online", action="store_true", help="force the LLM (requires an API key in env)"
    )
    parser.add_argument("--model", help="litellm model id, e.g. anthropic/claude-haiku-4-5")
    parser.add_argument("--ticks", type=int, help="max steps before giving up")
    parser.add_argument(
        "--delay", type=float, help="seconds between ticks (pacing for the console)"
    )
    parser.add_argument("--world", help="path to an ir-sim world YAML")
    parser.add_argument(
        "--graphics",
        choices=("auto", "half", "kitty"),
        default="auto",
        help="world rendering: 'half' block pixels (portable, recordable), 'kitty' bitmap "
        "graphics (smooth, needs Ghostty/Kitty/WezTerm), or 'auto' (default)",
    )
    parser.add_argument(
        "--no-live", action="store_true", help="disable the live cockpit (plain output)"
    )
    args = parser.parse_args(argv)

    offline = args.offline or (not args.online and not _has_api_key())
    os.environ["ELLIOT_OFFLINE"] = "1" if offline else "0"
    if args.model:
        os.environ["ELLIOT_MODEL"] = args.model
    if args.ticks is not None:
        os.environ["ELLIOT_MAX_TICKS"] = str(args.ticks)
    if args.delay is not None:
        os.environ["ELLIOT_TICK_DELAY"] = str(args.delay)
    if args.world:
        os.environ["ELLIOT_WORLD"] = args.world

    if args.online and not _has_api_key():
        print(
            "elliot: --online requested but no API key in the environment.\n"
            "        try:  envchain ai elliot --online\n"
            "        or run offline:  elliot --offline",
            file=sys.stderr,
        )
        return 2

    import asyncio

    from .driver import drive

    summary = asyncio.run(drive(live=not args.no_live, graphics=args.graphics))
    return 0 if summary["reached_ghost"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
