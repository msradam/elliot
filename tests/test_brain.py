from elliot.brain import ANGULAR_MAX, LINEAR_MAX, Brain, _plan
from elliot.world import World


def _perceive():
    return World().perceive()


def test_offline_decision_is_well_formed():
    d = Brain().deliberate("recon", _perceive(), {})
    assert LINEAR_MAX >= d.linear >= -0.5
    assert ANGULAR_MAX >= d.angular >= -ANGULAR_MAX
    assert d.next_action in {"boot", "recon", "exploit", "exfil", "ghost"}
    assert isinstance(d.thought, str) and d.thought


def test_non_moving_phases_hold_still():
    for phase in ("boot", "ghost"):
        d = Brain().deliberate(phase, _perceive(), {})
        assert d.linear == 0.0 and d.angular == 0.0


def test_eager_proposals_reach_ahead_of_the_gate():
    """Even with no gate flags set, Elliot reaches for the next phase early."""
    b = Brain()
    assert b.deliberate("boot", _perceive(), {}).next_action == "recon"
    # within sense_radius*1.8 but not yet located: he still reaches for exploit
    p = _perceive()
    near = type(p)(**{**p.__dict__, "distance": 4.0, "target": (0, 0)})
    assert b._reflex_next("recon", near, {"target_located": False}) == "exploit"


def test_planner_avoids_a_blocking_obstacle():
    # roll forward until the central obstacle is close, then the plan must steer off-axis
    w = World()
    b = Brain()
    for _ in range(40):
        p = w.perceive()
        if p.front_range < 1.0:
            break
        d = b.deliberate("recon", p, {})
        w.drive(d.linear, d.angular)
    steer, clear, boxed = _plan(w.perceive())
    assert clear >= 0.0
    # when something is right ahead, the chosen heading is not straight on
    if w.perceive().front_range < 0.8:
        assert abs(steer) > 0.1


def test_json_extraction_tolerates_fences_and_prose():
    b = Brain()
    assert b._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert b._extract_json('sure: {"a": 2} done') == {"a": 2}
    assert b._extract_json("no json here") is None
