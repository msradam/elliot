import asyncio

from elliot.driver import _fallback, drive


def test_fallback_keeps_working_the_current_phase():
    assert _fallback(["recon", "exploit"]) == "recon"
    assert _fallback(["exfil"]) == "exfil"
    assert _fallback([]) is None


def test_drive_runs_full_circuit_through_the_mcp_server():
    summary = asyncio.run(drive(live=False, max_ticks=300))
    assert summary["reached_ghost"] is True
    assert summary["final_phase"] == "ghost"
    assert summary["refusals"] > 0  # the machine pushed back on the eager reaches
