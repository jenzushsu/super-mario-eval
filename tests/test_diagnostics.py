from mario_eval.simulation import continuation_summary, selection_diagnostics


def test_partial_fatal_followups_are_not_complete_coverage():
    outcome = {
        "status": "alive",
        "dx": 10,
        "continuations": [
            {"id": name, "status": "dead", "frames": 1} for name in ("run", "jump", "run_jump")
        ],
    }
    summary = continuation_summary(outcome)
    assert summary["all_tested_fatal"]
    assert summary["coverage"] == "partial"
    assert summary["earliest_fatal_frames"] == 1
    outcome["continuations"].append({"id": "wait", "status": "alive", "frames": 52})
    assert not continuation_summary(outcome)["all_tested_fatal"]


def test_untested_and_no_progress_are_explicit():
    outcome = {"status": "alive", "dx": 0, "continuations": []}
    state = {
        "outcomes": {"run": outcome},
        "simulation": {"horizon": 48},
        "history": {"frames_since_best_x": 52},
    }
    result = selection_diagnostics(state, "run")
    assert result["incomplete_followup_coverage"]
    assert not result["all_tested_followups_fatal"]
    assert result["repeated_no_progress"]
    assert not result["immediate_death"]
    state["history"]["frames_since_best_x"] = 0
    assert not selection_diagnostics(state, "run")["repeated_no_progress"]
    outcome["status"] = "unknown"
    assert selection_diagnostics(state, "run")["unknown_outcome"]
    assert selection_diagnostics(state, "run")["incomplete_followup_coverage"]
