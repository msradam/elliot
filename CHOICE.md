# Simulation library: ir-sim

Decision: **ir-sim** (`pip install ir-sim`, version 2.10.0 at time of writing).

The robot needs to sense the world, the state machine needs something real to
read, and the whole thing has to run inside a terminal with no display server.
ir-sim is the only candidate that satisfies all four constraints without a
fight.

## The candidates, against the criteria

| | sensors (proximity/terrain) | meaningful state for the FSM | clean headless pip install | terminal-visualizable |
|---|---|---|---|---|
| **ir-sim** | 2D lidar, collision flags | pose, goal, arrive, collision, ranges | yes, `display=False, disable_all_plot=True` | yes (we render the state ourselves) |
| PyBullet | ray-cast sensors, contacts | full 6-DOF rigid-body state | installs, but DIRECT/headless is fiddly and 3D is overkill | needs custom camera-to-ascii |
| MuJoCo | rangefinders, touch, contacts | rich physics state | installs, but you author MJCF XML and wire sensors by hand | needs offscreen GL render |
| numpy grid (fallback) | whatever you write | whatever you write | trivially | trivially |

## Why ir-sim wins

It is purpose-built for exactly this shape of problem: a 2D mobile robot with
sensors navigating a world of obstacles toward a goal. That is the kill-chain
Elliot walks (recon the space, approach the target, exfil to the exit), so the
library's native vocabulary maps onto the FSM's vocabulary with no translation
layer.

Concretely, verified before committing (all headless, `MPLBACKEND=Agg`, no
window opened):

- `irsim.make(world, display=False, disable_all_plot=True)` builds a world from
  a small YAML file. No GUI, no display server, no blocking event loop.
- `env.step([[v], [w]])` advances a differential-drive robot one tick.
- `env.get_lidar_scan(0)["ranges"]` returns a real 2D lidar sweep (we use 36
  beams over 360 degrees, 4 m range). This is the **proximity / terrain sense**
  the FSM reads every tick.
- `env.robot_list[0]` exposes ground-truth `.state` (x, y, theta), `.goal`,
  `.arrive`, and `.collision`. These are the **honest gates** the state machine
  trusts: a phase can only advance when the physical flag says so, not when the
  LLM claims so.

That last point is the whole reason for a real simulator instead of a narrated
one. Elliot is eager; he reaches for the next phase the moment he believes he is
ready, ahead of the evidence. For the state machine's refusals to mean anything,
there has to be a ground truth underneath the LLM's beliefs that can disagree
with them. ir-sim's arrival flag is that ground truth. When the model reaches for
EXFIL but `.arrive` is still `False`, Theodosia refuses the transition and hands
back the moves he has actually earned. The simulator is what makes the gate
falsifiable: the FSM is in control precisely because the world, not the model,
decides when a transition is allowed.

## Why not the others

- **PyBullet / MuJoCo** are physics engines. They are more capable than this
  project needs and more setup than this project wants. Both push you toward 3D
  rigid-body dynamics, articulated URDF/MJCF authoring, and offscreen GL or
  camera rendering to get anything on screen. For a 2D navigator driven by an
  FSM whose only display is a terminal, that capability is pure overhead. The
  prompt's own criterion is "the most meaningful robot simulation for the least
  setup friction"; these two lose on the friction side.
- **Plain numpy grid** loses on the meaning side. It would install in zero
  seconds and render trivially, but every sensor, every collision rule, and
  every kinematic update would be code we wrote, which means the FSM would only
  ever be reading a world we hand-authored to be readable. ir-sim gives us a
  lidar return and a continuous-space differential-drive model we did not write
  and cannot quietly cheat, which is what makes the robot's state worth
  verifying. We keep numpy/Rich for **rendering** the world to the terminal, not
  for being the world.

## What we do not use from ir-sim

ir-sim can open its own matplotlib animation window. We never do. Elliot's
display is the terminal (Rich, green on black), and we draw it ourselves from
the same ground-truth state the FSM reads, so the operator sees exactly what
Elliot sees. ir-sim is the world and the senses; it is not the screen.
