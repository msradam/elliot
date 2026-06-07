"""my console: a live, green-on-black cockpit drawn with rich.

two things on screen at once, which is the whole point: me in my world, and the
phase of the circuit that is lit. around them, the raw sensor read and a log of
what i am thinking, what i reach for, and where the machine tells me no.

the cockpit holds no sim state. it reads the live :class:`World` for geometry
and is fed the machine's state each tick by the driver.
"""

from __future__ import annotations

import math
from collections import deque

from rich.align import Align
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from .persona import CIRCUIT_ORDER, PHASES
from .world import World

# half-block "pixel" display: each cell is two stacked pixels (``▀``, a
# foreground for the top and a background for the bottom), which doubles the
# vertical resolution and keeps colour. green for me and my wake, grey for the
# walls, amber for the target.
_PX = {
    "wall_core": "grey27",  # three bands give the obstacle a soft, rounded edge
    "wall": "grey42",
    "wall_rim": "grey54",
    "wake": ["color(22)", "color(28)", "color(34)", "color(40)", "color(46)"],  # dim -> bright
    "robot": "bright_green",
    "nose": ["color(85)", "color(43)"],  # short heading marker ahead of the head
    "goal": "gold3",
    "goal_hot": "bright_yellow",
    "goal_halo": "dark_goldenrod",
    "origin": "dark_cyan",
    "collision": "bright_red",
    "ghost": "grey42",
}

# how many recent positions make up the wake i leave behind me.
_WAKE = 26


class Cockpit:
    """holds the log and the latest frame; draws the whole dashboard."""

    def __init__(self, world: World, model: str, grid_cols: int = 46, grid_rows: int = 22) -> None:
        self.world = world
        self.model = model
        self.cols = grid_cols
        self.rows = grid_rows
        self.log: deque[Text] = deque(maxlen=400)
        self.frame: dict = {}
        self.valid: list[str] = []
        self.steps = 0
        self.refusals = 0
        self._stream: tuple[str, str] | None = None  # (phase, partial narration)

    def stream(self, phase: str, text: str) -> None:
        """set the half-typed narration the console is showing right now."""
        self._stream = (phase, text)

    def note(self, text: str, style: str = "green") -> None:
        tick = self.frame.get("tick", 0)
        line = Text()
        line.append(f"{tick:>4} ", style="grey42")
        line.append(text, style=style)
        self.log.append(line)

    def record_refusal(self, phase: str, reached_for: str, valid: list[str]) -> None:
        self.refusals += 1
        allowed = ", ".join(valid) or "nothing"
        self.note(
            f"REFUSED  reached for '{reached_for}' from {phase}; not earned. allowed: {allowed}",
            style="bold red",
        )

    def record_step(self, state: dict, valid: list[str], action: str) -> None:
        self.frame = state
        self.valid = valid
        self.steps += 1
        self._stream = None  # the line is committed to the log now
        phase = state.get("phase", action)
        thought = state.get("thought", "")
        if len(thought) > 104:  # keep each log entry to a single line
            thought = thought[:101].rstrip() + "..."
        src = state.get("source", "")
        tag = "·" if src == "llm" else "~"  # ~ marks the reflex/offline navigator
        style = "bold bright_green" if phase == "ghost" else "green"
        self.note(f"{phase.upper():<8}{tag} {thought}", style=style)

    def renderable(self) -> Layout:
        root = Layout()
        root.split_column(
            Layout(self._header(), name="header", size=4),
            Layout(name="body"),
            Layout(self._console_panel(), name="log", size=11),
        )
        root["body"].split_row(
            Layout(self._world_panel(), name="world", ratio=3),
            Layout(name="side", ratio=2),
        )
        root["body"]["side"].split_column(
            Layout(self._circuit_panel(), name="circuit", size=11),
            Layout(self._sensors_panel(), name="sensors"),
        )
        return root

    def _header(self) -> Panel:
        bar = Text()
        bar.append("ELLIOT", style="bold bright_green")
        bar.append("  // hello, friend\n", style="green")
        bar.append(f"model {self.model}", style="grey50")
        bar.append("   tick ", style="grey50")
        bar.append(f"{self.frame.get('tick', 0):>4}", style="bright_green")
        bar.append("   steps ", style="grey50")
        bar.append(f"{self.steps:>3}", style="bright_green")
        bar.append("   refusals ", style="grey50")
        bar.append(f"{self.refusals:>3}", style="red")
        return Panel(bar, border_style="green", padding=(0, 1))

    def _world_panel(self) -> Panel:
        body = self._pixel_world()
        legend = Text("\n")
        for label, color in (
            ("target", _PX["goal_hot"]),
            ("elliot", _PX["robot"]),
            ("obstacle", _PX["wall"]),
            ("wake", _PX["wake"][3]),
            ("exfil", _PX["origin"]),
        ):
            legend.append("▀ ", style=color)
            legend.append(f"{label}   ", style="grey42")
        return Panel(
            Group(Align.center(body), Align.center(legend)),
            title="[green]the world[/]",
            border_style="green",
            padding=(0, 1),
        )

    def _pixel_world(self) -> Text:
        """draw the world as a colour half-block image (two pixels per cell)."""
        cols, rows = self.cols, self.rows
        ph = rows * 2  # pixel rows
        W, H = self.world.width, self.world.height
        scale = min(cols / W, ph / H)  # pixels per metre, preserving aspect
        pw, phh = max(1, round(W * scale)), max(1, round(H * scale))
        offx, offy = (cols - pw) // 2, (ph - phh) // 2
        grid: list[list[str | None]] = [[None] * cols for _ in range(ph)]

        def put(py: int, px_: int, color: str, *, over: bool = True) -> None:
            if 0 <= py < ph and 0 <= px_ < cols and (over or grid[py][px_] is None):
                grid[py][px_] = color

        def to_px(wx: float, wy: float) -> tuple[int, int]:
            return (
                offy + int(round((H - wy) / H * (phh - 1))),
                offx + int(round(wx / W * (pw - 1))),
            )

        step = W / pw  # world metres per pixel, for edge detection
        for owx, owy, orad in self.world.obstacles():
            for py in range(offy, offy + phh):
                for px_ in range(offx, offx + pw):
                    wx = (px_ - offx) / max(pw - 1, 1) * W
                    wy = H - (py - offy) / max(phh - 1, 1) * H
                    d = math.hypot(wx - owx, wy - owy)
                    if d <= orad:
                        if d >= orad - step:
                            put(py, px_, _PX["wall_rim"])
                        elif d >= orad - 2 * step:
                            put(py, px_, _PX["wall"])
                        else:
                            put(py, px_, _PX["wall_core"])

        # a short fading wake of where i have just been, only behind me, not the
        # whole route, so the bright head reads as the leading end and nothing
        # glows out front to confuse you.
        wake = self.world.trail[-(_WAKE + 1) : -1]
        ramp = _PX["wake"]
        for i, (tx, ty) in enumerate(wake):
            color = ramp[min(len(ramp) - 1, i * len(ramp) // max(len(wake), 1))]
            put(*to_px(tx, ty), color, over=False)

        put(*to_px(*self.world.origin), _PX["origin"])

        gy, gx = to_px(*self.world.goal)
        pulse = self.frame.get("tick", 0) % 2 == 0
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            put(gy + dy, gx + dx, _PX["goal_halo"], over=False)
        put(gy, gx, _PX["goal_hot"] if pulse else _PX["goal"])

        p = self.frame.get("perception") or {}
        pos = p.get("position")
        if pos:
            ry, rx = to_px(pos[0], pos[1])
            theta = math.radians(p.get("heading_deg", 0.0))
            phase = self.frame.get("phase", "")
            moving = phase != "ghost" and not p.get("collision")
            if moving:  # a short bright nose ahead of the head, showing heading
                for k, color in zip((1, 2), _PX["nose"]):
                    put(ry - round(math.sin(theta) * k), rx + round(math.cos(theta) * k), color)
            if p.get("collision"):
                robot = _PX["collision"]
            elif phase == "ghost":
                robot = _PX["ghost"]
            else:
                robot = _PX["robot"]
            put(ry, rx, robot)

        body = Text()
        for r in range(rows):
            top, bottom = grid[2 * r], grid[2 * r + 1]
            for c in range(cols):
                t, b = top[c], bottom[c]
                if t is None and b is None:
                    body.append(" ")
                elif b is None:
                    body.append("▀", style=t)
                elif t is None:
                    body.append("▄", style=b)
                else:
                    body.append("▀", style=f"{t} on {b}")
            if r < rows - 1:
                body.append("\n")
        return body

    def world_png(self, side: int = 760) -> bytes:
        """draw the world as a smooth anti-aliased png (for the kitty mode).

        rendered at triple size and downsampled, so the circles and the wake get
        clean edges no half-block grid can match. same scene as the pixel world:
        grey obstacles, a green wake fading behind me, a pulsing amber target.
        """
        from io import BytesIO

        from PIL import Image, ImageDraw

        ss = 3
        s = side * ss
        w, h = self.world.width, self.world.height
        img = Image.new("RGB", (s, s), (6, 9, 6))
        draw = ImageDraw.Draw(img, "RGBA")

        def xy(wx: float, wy: float) -> tuple[float, float]:
            return wx / w * (s - 1), (h - wy) / h * (s - 1)

        def rad(r: float) -> float:
            return r / w * s

        for owx, owy, orad in self.world.obstacles():
            cx, cy = xy(owx, owy)
            rr = rad(orad)
            draw.ellipse(
                [cx - rr, cy - rr, cx + rr, cy + rr],
                fill=(62, 66, 62),
                outline=(108, 114, 108),
                width=round(2.4 * ss),
            )

        wake = [xy(x, y) for x, y in self.world.trail[-(_WAKE + 1) : -1]]
        for i in range(len(wake) - 1):
            f = (i + 1) / len(wake)
            draw.line(
                [wake[i], wake[i + 1]],
                fill=(int(36 + f * 58), int(86 + f * 150), int(40 + f * 70), int(110 + f * 145)),
                width=round(2.2 * ss),
            )

        ox, oy = xy(*self.world.origin)
        orr = rad(0.17)
        draw.ellipse([ox - orr, oy - orr, ox + orr, oy + orr], fill=(38, 150, 165))

        gx, gy = xy(*self.world.goal)
        for gr, alpha in ((rad(0.7), 38), (rad(0.45), 95), (rad(0.27), 165)):
            draw.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=(255, 205, 70, alpha))
        hot = self.frame.get("tick", 0) % 2 == 0
        cr = rad(0.15)
        draw.ellipse(
            [gx - cr, gy - cr, gx + cr, gy + cr],
            fill=(255, 236, 120) if hot else (235, 190, 60),
        )

        p = self.frame.get("perception") or {}
        pos = p.get("position")
        if pos:
            rx, ry = xy(*pos)
            theta = math.radians(p.get("heading_deg", 0.0))
            phase = self.frame.get("phase", "")
            if phase != "ghost" and not p.get("collision"):
                draw.line(
                    [
                        (rx, ry),
                        (rx + math.cos(theta) * rad(0.55), ry - math.sin(theta) * rad(0.55)),
                    ],
                    fill=(150, 255, 185),
                    width=round(2.0 * ss),
                )
            rr = rad(0.16)
            if p.get("collision"):
                color = (255, 80, 80)
            elif phase == "ghost":
                color = (120, 120, 120)
            else:
                color = (90, 255, 132)
            draw.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], fill=color)

        img = img.resize((side, side), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def _circuit_panel(self) -> Panel:
        phase = self.frame.get("phase", "boot")
        flags = [
            ("verified", self.frame.get("sensors_verified")),
            ("located", self.frame.get("target_located")),
            ("reached", self.frame.get("target_reached")),
            ("clear", self.frame.get("exfil_complete")),
        ]
        line = Text()
        for i, name in enumerate(CIRCUIT_ORDER):
            meta = PHASES[name]
            lit = name == phase
            line.append(
                f"{meta.glyph}{meta.title}", style="reverse bold bright_green" if lit else "grey42"
            )
            if i < len(CIRCUIT_ORDER) - 1:
                line.append(" ▸ ", style="green" if lit else "grey27")

        flag_line = Text("  ", style="grey42")
        for name, on in flags:
            flag_line.append(
                f"{'✓' if on else '·'} {name}  ", style="bright_green" if on else "grey30"
            )

        reaching = self.frame.get("proposed_next", "")
        reach_line = Text()
        reach_line.append("\n  reaching for ", style="grey42")
        reach_line.append(reaching, style="bold green")
        reach_line.append("   allowed: ", style="grey42")
        reach_line.append(", ".join(self.valid) or "—", style="cyan")

        return Panel(
            Group(line, Text(), flag_line, reach_line),
            title="[green]the circuit[/]",
            border_style="green",
            padding=(0, 1),
        )

    def _sensors_panel(self) -> Panel:
        p = self.frame.get("perception") or {}
        rows = [
            ("position", str(p.get("position", "—"))),
            ("heading", f"{p.get('heading_deg', 0)}°"),
            ("objective", str(p.get("target", "—"))),
            ("distance", f"{p.get('distance_to_target_m', '—')} m"),
            ("bearing", f"{p.get('bearing_to_target_deg', '—')}°"),
            ("nearest obst", f"{p.get('nearest_obstacle_m', '—')} m"),
            ("ahead", f"{p.get('obstacle_ahead_m', '—')} m"),
            ("collision", "YES" if p.get("collision") else "no"),
            ("arrival flag", "SET" if p.get("arrival_flag") else "unset"),
        ]
        body = Text()
        for k, v in rows:
            body.append(f"{k:>13}  ", style="grey50")
            danger = (k == "collision" and v == "YES") or (
                k == "ahead"
                and isinstance(p.get("obstacle_ahead_m"), (int, float))
                and p["obstacle_ahead_m"] < 0.4
            )
            body.append(f"{v}\n", style="bold red" if danger else "bright_green")
        return Panel(body, title="[green]sensors[/]", border_style="green", padding=(0, 1))

    def _console_panel(self) -> Panel:
        keep = 8 if self._stream else 9
        lines = list(self.log)[-keep:]
        if self._stream:
            phase, text = self._stream
            tick = self.frame.get("tick", 0)
            live = Text()
            live.append(f"{tick:>4} ", style="grey42")
            live.append(f"{phase.upper():<8}· ", style="green")
            live.append(text[-92:], style="bright_green")
            live.append("▌", style="bold bright_green")  # the cursor, still typing
            lines.append(live)
        body = Text("\n").join(lines) if lines else Text("...", style="grey42")
        return Panel(body, title="[green]elliot://console[/]", border_style="green", padding=(0, 1))
