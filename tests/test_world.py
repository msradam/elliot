import math

from elliot.world import World


def test_world_builds_headless_and_perceives():
    w = World()
    p = w.perceive()
    assert len(p.ranges) == 36
    assert math.isfinite(p.min_range)
    assert p.front_range >= 0
    assert p.distance > 0  # the goal is not at the start
    assert p.target_label == "target"
    assert not p.collision


def test_drive_moves_the_robot():
    w = World()
    before = w.perceive().pose
    for _ in range(5):
        w.drive(1.0, 0.0)
    after = w.perceive().pose
    assert math.hypot(after[0] - before[0], after[1] - before[1]) > 0.1


def test_hold_keeps_position():
    w = World()
    before = w.perceive().pose
    w.hold()
    after = w.perceive().pose
    assert math.isclose(before[0], after[0], abs_tol=1e-6)
    assert math.isclose(before[1], after[1], abs_tol=1e-6)


def test_begin_exfil_flips_objective_to_origin():
    w = World()
    assert not w.exfil_active
    w.begin_exfil()
    assert w.exfil_active
    p = w.perceive()
    assert p.target_label == "exfil point"
    # objective is now the origin Elliot booted from
    assert math.hypot(p.target[0] - w.origin[0], p.target[1] - w.origin[1]) < 1e-6


def test_perception_summary_is_json_friendly():
    import json

    summary = World().perceive().summary()
    json.dumps(summary)  # must not raise
    assert "obstacle_ahead_m" in summary
    assert "arrival_flag" in summary
