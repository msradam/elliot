"""the driver: an mcp client that runs the circuit and draws it.

each tick it proposes the phase the last action wrote into state, calls the
``step`` tool, and on a refusal takes an allowed move from ``valid_next_actions``
instead. like :func:`theodosia.drive_claude`, but model-agnostic (the model runs
inside the actions, through litellm) and wired to the cockpit.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import warnings

from .brain import Brain
from .config import CONFIG
from .console import Cockpit
from .fsm import mount_server
from .world import World


def _quiet() -> None:
    """shut the libraries up so their chatter never corrupts the live display."""
    os.environ.setdefault("MPLBACKEND", "Agg")
    for name in ("theodosia", "fastmcp", "mcp", "FastMCP", "LiteLLM", "litellm", "httpx"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore")
    try:  # ir-sim logs through loguru, which stdlib logging cannot reach
        from loguru import logger as _loguru

        _loguru.disable("irsim")
    except Exception:
        pass


def _fallback(valid: list[str]) -> str | None:
    """the disciplined choice when my reach is refused: keep working the phase i
    am in (the self-loop is always first in the valid set)."""
    return valid[0] if valid else None


async def drive(
    *,
    world: World | None = None,
    brain: Brain | None = None,
    max_ticks: int | None = None,
    tick_delay: float | None = None,
    live: bool = True,
    graphics: str = "auto",
) -> dict:
    """run the circuit to ghost (or the tick cap). returns a run summary."""
    _quiet()
    world = world or World()
    brain = brain or Brain()
    max_ticks = max_ticks if max_ticks is not None else CONFIG.max_ticks
    tick_delay = tick_delay if tick_delay is not None else CONFIG.tick_delay

    label = CONFIG.model + ("  (offline reflex)" if CONFIG.offline else "")
    cockpit = Cockpit(world, label)

    from fastmcp import Client

    summary = {
        "steps": 0,
        "refusals": 0,
        "reached_ghost": False,
        "final_phase": "boot",
    }

    async with Client(mount_server(world, brain)) as client:
        await _cold_start(client, cockpit)
        proposed: str | None = "boot"

        renderer = _select_renderer(cockpit, live, graphics)
        # stream the narration in live. inside a recording, screen-mode Live
        # repaints per token and bloats the cast, so skip it there unless
        # ELLIOT_FORCE_STREAM insists.
        recording = os.environ.get("ASCIINEMA_SESSION") and not os.environ.get(
            "ELLIOT_FORCE_STREAM"
        )
        if live and not CONFIG.offline and not recording:
            brain.on_stream = lambda phase, text: (
                cockpit.stream(phase, text),
                renderer.update(text_only=True),
            )
        with renderer:
            for _tick in range(max_ticks):
                if proposed is None:
                    break

                result = await client.call_tool("step", {"action": proposed, "inputs": {}})
                payload = result.structured_content or {}

                if payload.get("error"):
                    valid = payload.get("valid_next_actions", [])
                    cockpit.record_refusal(cockpit.frame.get("phase", "boot"), proposed, valid)
                    renderer.update()
                    proposed = _fallback(valid)
                    await asyncio.sleep(tick_delay)
                    continue

                state = payload["state"]
                valid = payload["valid_next_actions"]
                cockpit.record_step(state, valid, payload["action"])
                renderer.update()
                summary["final_phase"] = state.get("phase", proposed)

                if not valid:  # terminal: GHOST
                    cockpit.note("gone. no one was watching the watcher.", "bold bright_green")
                    renderer.update()
                    summary["reached_ghost"] = True
                    break

                proposed = state.get("proposed_next") or _fallback(valid)
                await asyncio.sleep(tick_delay)

    summary.update(
        steps=cockpit.steps,
        refusals=cockpit.refusals,
        log_tail=[line.plain for line in list(cockpit.log)[-14:]],
    )
    _print_epilogue(cockpit, summary, full=live)
    return summary


async def _cold_start(client, cockpit: Cockpit) -> None:
    """read the circuit map once at session start, before i trust it."""
    cockpit.note("cold boot. reading the circuit map before i trust it.", "bright_green")
    try:
        res = await client.read_resource("theodosia://graph")
        if res and getattr(res[0], "text", ""):
            cockpit.note("circuit loaded. boot, recon, exploit, exfil, ghost.", "grey50")
    except Exception:
        pass


def _select_renderer(cockpit: Cockpit, live: bool, graphics: str):
    """pick the renderer: none, half-block (rich), or kitty bitmap graphics."""
    if not live:
        return _LiveRenderer(cockpit, enabled=False)
    from .graphics import resolve_graphics

    if resolve_graphics(graphics) == "kitty":
        try:
            import PIL  # noqa: F401  (the Kitty renderer needs Pillow)

            return _KittyRenderer(cockpit)
        except Exception:
            pass
    return _LiveRenderer(cockpit, enabled=True)


class _LiveRenderer:
    """wraps rich.live.Live (the half-block cockpit), or no-ops when disabled."""

    def __init__(self, cockpit: Cockpit, enabled: bool) -> None:
        self.cockpit = cockpit
        self.enabled = enabled
        self._live = None

    def __enter__(self):
        if self.enabled:
            from rich.live import Live

            # one repaint per tick (auto_refresh off) keeps a recording small. a
            # full-screen Layout left to auto-refresh would emit thousands of
            # redundant frames.
            self._live = Live(
                self.cockpit.renderable(), screen=True, auto_refresh=False, transient=False
            )
            self._live.__enter__()
        return self

    def update(self, text_only: bool = False) -> None:
        if self._live is not None:
            self._live.update(self.cockpit.renderable(), refresh=True)

    def __exit__(self, *exc):
        if self._live is not None:
            self._live.__exit__(*exc)


class _KittyRenderer:
    """composite the screen by hand: a bitmap world, text panels around it.

    each tick redraws the header, places the world png through the kitty graphics
    protocol, and lays the circuit and console panels around it with absolute
    cursor moves.
    """

    IMG_COLS = 44
    IMG_ROWS = 22

    def __init__(self, cockpit: Cockpit) -> None:
        self.cockpit = cockpit
        self._out = sys.stdout

    def __enter__(self):
        self._write("\x1b[?1049h\x1b[2J\x1b[?25l")  # alt screen, clear, hide cursor
        return self

    def update(self, text_only: bool = False) -> None:
        import shutil

        from .graphics import delete_images, place_image

        width, _height = shutil.get_terminal_size((124, 44))
        buf: list[str] = ["\x1b[H"]

        header = self._lines(self.cockpit._header(), width)
        self._place(buf, 1, 1, header)

        # the bitmap world already shows position and heading, so the sensor
        # panel is dropped here to keep the image big and everything on one
        # screen. while the narration streams, text_only leaves the last image
        # alone so the png is not resent on every token.
        img_row = len(header) + 1
        if not text_only:
            img_col = max(1, (width - self.IMG_COLS) // 2)
            buf.append(f"\x1b[{img_row};{img_col}H")
            buf.append(delete_images())
            buf.append(place_image(self.cockpit.world_png(), self.IMG_COLS, self.IMG_ROWS))

        below = img_row + self.IMG_ROWS
        circuit = self._lines(self.cockpit._circuit_panel(), width)
        self._place(buf, below, 1, circuit)

        log_row = below + len(circuit)
        self._place(buf, log_row, 1, self._lines(self.cockpit._console_panel(), width))
        buf.append("\x1b[0J")  # clear anything below the log
        self._write("".join(buf))

    def __exit__(self, *exc):
        from .graphics import delete_images

        self._write(delete_images() + "\x1b[?25h\x1b[?1049l")

    def _write(self, text: str) -> None:
        self._out.write(text)
        self._out.flush()

    @staticmethod
    def _lines(renderable, width: int) -> list[str]:
        import io

        from rich.console import Console

        sink = Console(
            file=io.StringIO(), force_terminal=True, color_system="truecolor", width=width
        )
        sink.print(renderable, end="")
        return sink.file.getvalue().split("\n")

    @staticmethod
    def _place(buf: list[str], row: int, col: int, lines: list[str]) -> None:
        for i, line in enumerate(lines):
            buf.append(f"\x1b[{row + i};{col}H{line}")


def _print_epilogue(cockpit: Cockpit, summary: dict, full: bool = True) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    out = Console()
    if full:
        out.print(cockpit.renderable())
    else:  # no-live mode: show the tail of Elliot's console so the run isn't silent
        for line in list(cockpit.log)[-12:]:
            out.print(line)
    verdict = Text()
    end = "GHOST" if summary["reached_ghost"] else summary["final_phase"].upper()
    verdict.append("run complete  ", style="bold bright_green")
    verdict.append(
        f"ended at {end}   {summary['steps']} steps   {summary['refusals']} refusals",
        style="green",
    )
    out.print(Panel(verdict, border_style="green"))
