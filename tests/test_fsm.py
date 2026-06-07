from theodosia._introspect import valid_next_action_names

from elliot.brain import Brain
from elliot.fsm import _TRANSITIONS, build_application, initial_state
from elliot.world import World


def _fresh_app():
    return build_application(World(), Brain(), with_tracker=False)


def _run(app, max_ticks=300):
    """Drive the app the way the driver does: propose, validate, fall back."""
    proposed = "boot"
    phases, refusals = [], 0
    for _ in range(max_ticks):
        valid = valid_next_action_names(app)
        if not valid:
            return phases, refusals, True
        if proposed in valid:
            target = proposed
        else:
            refusals += 1
            target = valid[0]
        act = app.graph.get_action(target)
        app.get_next_action = lambda a=act: a
        _, _res, state = app.step()
        app.get_next_action = type(app).get_next_action.__get__(app)
        phases.append(state["phase"])
        proposed = state["proposed_next"]
    return phases, refusals, False


def test_entrypoint_is_boot_and_only_boot_is_reachable_first():
    app = _fresh_app()
    assert app.entrypoint == "boot"
    assert valid_next_action_names(app) == ["boot"]


def test_machine_refuses_unearned_transitions():
    """From boot, with sensors unverified, EXFIL is not on the menu."""
    app = _fresh_app()
    assert "exfil" not in valid_next_action_names(app)
    assert "exploit" not in valid_next_action_names(app)


def test_full_circuit_reaches_ghost_with_refusals():
    phases, refusals, terminal = _run(_fresh_app())
    assert terminal, "circuit should reach a terminal (ghost) state"
    # the eager reaches get refused before the gates open
    assert refusals > 0
    # the spine, in order
    ordered = [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p]
    for phase in ("boot", "recon", "exploit", "exfil", "ghost"):
        assert phase in ordered
    assert ordered.index("recon") < ordered.index("exploit") < ordered.index("exfil")


def test_circuit_is_a_linear_spine_with_no_fault_node():
    nodes = {f for f, _t, *_ in _TRANSITIONS} | {t for _f, t, *_ in _TRANSITIONS}
    assert nodes == {"boot", "recon", "exploit", "exfil", "ghost"}


def test_initial_state_has_all_gates_unset():
    s = initial_state()
    assert s["phase"] == "boot"
    assert not any(
        s[k]
        for k in (
            "sensors_verified",
            "target_located",
            "target_reached",
            "exfil_complete",
        )
    )
