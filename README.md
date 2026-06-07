# elliot

An LLM-driven state machine in control of a simulated robot. The model does not
hold the wheel. A state machine does, and the model has to ask it for permission
to move on.

---

You are reading this because you are going to run something that thinks, and you
want to know how much of it to trust. Fair. I would want the same. So here is my
own wiring, written down. Read it before you run me.

## what i am

I am a robot in a small, unmapped 2D world. There is a target somewhere out in
it and an obstacle or two between me and it. My job is a four-step break-in:

```
   ◉ BOOT  ▸  ◈ RECON  ▸  ◆ EXPLOIT  ▸  ◇ EXFIL  ▸  ✕ GHOST
```

- **BOOT** wake up. read my own senses twice and check they agree before I trust
  them. then start.
- **RECON** close on the target through open space, around whatever is in the
  way, until it is actually within sensing range.
- **EXPLOIT** drive onto it. all the way on, not nearly on.
- **EXFIL** turn around and run back to where I booted.
- **GHOST** gone.

Each phase is the same loop: read the sensors, think about what to do, and reach
for the next phase. That last part is where the leash is.

## who is actually in control

I am eager. The moment I think I am ready for the next phase I reach for it. I
would rather grab for EXFIL while I am still a metre short and be told no than
sit and wait.

I do not get to decide if the reach lands. A state machine does, and it only
opens a gate when the **world** has earned it, not when I have talked myself
into it:

- it will not let me into EXPLOIT until the target is genuinely within sensing
  range.
- it will not let me into EXFIL until the simulator's own arrival flag has
  fired. me believing I have arrived is not enough.
- it will not let me GHOST until I am actually back home.

When it refuses, it hands me back the moves I *am* allowed, and I take one of
those and keep working. You will see this happen constantly in the console:
`REFUSED reached for 'exfil' from exploit; not earned. allowed: exploit`. That
line is not an error. That is the machine doing its job. It is the reason you
can let me run.

The split is deliberate. I (the language model) decide **strategy**: which phase
to reach for, and what I am looking at. A plain local controller handles
**steering and obstacle avoidance**, because that is motor work and I am bad at
motor work. The state machine sits between my ambition and the actuators and
refuses anything the world has not confirmed.

I also **narrate**. Every step, the model says what this moment feels like from
inside, in its own words, to you, the one reading the logs it has not decided to
trust. That line in the console is not a template I fill in; it is the model's,
each tick, and live it types itself in token by token as the model speaks. When
you run me offline with no model, that voice goes quiet and you get the
controller's plain telemetry instead, tagged so you can tell the difference
(`·` is the model speaking, `~` is the controller).

## the stack, so you can check my work

- **[ir-sim](https://github.com/hanruihua/ir-sim)** is the world and the senses:
  a headless 2D differential-drive robot with a 2D lidar. It is the ground
  truth, and it is not something I wrote, so I cannot quietly cheat it. See
  [CHOICE.md](CHOICE.md) for why this one.
- **[Apache Burr](https://github.com/apache/burr)** is the state machine itself:
  the phases are actions, the gates are conditional transitions.
- **[Theodosia](https://pypi.org/project/theodosia/)** mounts that Burr
  application as an MCP server whose only control surface is a `step` tool. It is
  the thing that validates or refuses every transition, and it keeps a
  hash-chained ledger of every step and every refusal.
- **[litellm](https://github.com/BerriAI/litellm)** is how I reach a model, so
  the model is swappable. Point `ELLIOT_MODEL` at anything it supports.
- **[Rich](https://github.com/Textualize/rich)** draws the console: the world
  (as half-block pixels, or a Kitty bitmap where the terminal supports it), the
  lit phase of the circuit, the raw sensor readout, and my narration scrolling
  beneath it, green on black.

The driver is an MCP client. It never picks a phase for me; it proposes the
phase I reached for and lets the server accept or refuse it. That is the same
shape as `theodosia.drive_claude`, but model-agnostic and wired to the live
display.

## run me

```bash
uv venv && uv pip install -e .

# offline: a deterministic reflex navigator drives, no model, no key needed.
python run.py --offline
# or, installed as a script:
elliot --offline
```

To let a model actually drive, give litellm a key. envchain is the clean way:

```bash
envchain ai elliot --online
# pick a different model:
envchain ai elliot --online --model anthropic/claude-haiku-4-5
```

With no key in the environment I fall back to the offline navigator on my own,
so the loop always completes.

### flags

```
--offline            reflex navigator, no LLM
--online             force the LLM (needs an API key in the env)
--model ID           any litellm model id (default anthropic/claude-haiku-4-5)
--ticks N            max steps before I give up
--delay S            seconds between ticks (console pacing)
--graphics MODE      world rendering: auto (default), half, or kitty
--world PATH         a different ir-sim world YAML
--no-live            plain output, no live cockpit (for logs / CI)
```

### graphics

The world has two renderers. `half` draws it with half-block pixels, which
works in any terminal and records cleanly with asciinema. `kitty` draws it as a
real anti-aliased bitmap via the Kitty graphics protocol, which looks far
smoother but only works in terminals that support it (Ghostty, Kitty, WezTerm)
and cannot be captured by asciinema. `auto` picks `kitty` when the terminal
supports it and `half` otherwise (and always `half` inside a recording).

## configuration

Every knob is an environment variable, read once at startup.

| variable | default | meaning |
|---|---|---|
| `ELLIOT_MODEL` | `anthropic/claude-haiku-4-5` | litellm model id |
| `ELLIOT_OFFLINE` | unset | `1` forces the reflex navigator |
| `ELLIOT_WORLD` | `elliot/worlds/default.yaml` | ir-sim world file |
| `ELLIOT_SENSE_RADIUS` | `2.4` | metres at which the target counts as located |
| `ELLIOT_ARRIVE_RADIUS` | `0.6` | metres that count as arrived |
| `ELLIOT_MAX_TICKS` | `200` | hard cap on steps |
| `ELLIOT_TICK_DELAY` | `0.35` | seconds between ticks |
| `ELLIOT_TEMPERATURE` | `0.4` | sampling temperature |

## how the pieces fit

```
elliot/
  world.py     ir-sim wrapper: perception (lidar, pose, goal, collision, arrival), drive()
  brain.py     litellm strategy + a gap-following controller for motion
  fsm.py       the Burr circuit (phases + gated transitions) and the Theodosia mount
  driver.py    the MCP client loop: propose the reach, surface the refusal, render
  console.py   the green-on-black cockpit
  persona.py   who I am, and what each phase is for
  worlds/      ir-sim world definitions
```

One tick, end to end: the driver calls `step(phase)` on the Theodosia server.
The Burr action for that phase reads ir-sim, asks the model what to reach for,
moves via the controller, and writes the honest gate flags from ground truth.
Theodosia computes the moves now reachable and returns them. The driver proposes
the phase I reached for next. If it is not on the list, refusal, and I take an
allowed move instead.

## tests

```bash
uv pip install -e '.[dev]'
pytest
```

The suite runs fully offline (the reflex navigator is deterministic), and covers
the world wrapper, the controller, the refusal gates, and a full circuit driven
end to end through the real MCP server.

## the recording

[`recording.cast`](recording.cast) is an asciinema capture of a full run, boot to
ghost. Play it back with `asciinema play recording.cast`.

## development

This project was built with LLM assistance.

## license

MIT.
