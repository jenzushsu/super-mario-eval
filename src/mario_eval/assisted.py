from __future__ import annotations

import argparse
import copy
import hashlib
import json
import threading
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .concurrency import FramePacer, run_workers
from .rankers import ProviderError, Ranker, payload_for
from .reporting import SCHEMA, Journal, new_run, provenance, report, write_json
from .simulation import (
    ACTION_SET,
    EVIDENCE_VERSION,
    BudgetStop,
    MarioSimulator,
    SimulationConfig,
    WorkBudget,
    canonical_state,
    selection_diagnostics,
    survival_selection,
)


class Display:
    """Reuse the existing paired desktop view; the search baseline stays in the report."""

    def __init__(self, enabled, offline):
        self.owner = threading.get_ident()
        self.lock = threading.Lock()
        self.view = None
        self.rows = []
        self.cancelled = False
        self.context = "Assisted outcome ranking"
        if enabled:
            from .cli import View

            self.view = View(
                "Assisted outcome ranking · Same simulation budget · Q to stop"
                + (" · OFFLINE" if offline else "")
            )

    def refresh(self, force=False):
        if threading.get_ident() != self.owner:
            return self.cancelled
        if self.view and self.rows:
            with self.lock:
                rows = [dict(row) for row in self.rows[:2]]
            self.cancelled |= not self.view.draw(rows, "Assisted")
        return self.cancelled

    def update(self, lane, status):
        with self.lock:
            lane["display"].update(
                frame=lane["sim"].frame.copy(),
                status=status,
                best_x=lane["sim"].best_x,
                reward=lane["sim"].reward,
            )
        self.refresh()

    def finish(self, args):
        if not self.view:
            return
        self.view.subtitle = f"{self.context} · Run finished · Q to close"
        self.refresh(force=True)
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            self.view.pg.image.save(self.view.screen, str(args.screenshot))
        if not args.exit_when_done:
            while not self.refresh(force=True):
                time.sleep(0.05)

    def close(self):
        if self.view:
            self.view.close()


def choose_with_events(lane, canonical, display):
    policy = lane["ranker"].provider
    remaining = lane["deadline"] - time.monotonic()
    if remaining <= 0:
        raise BudgetStop("wall_time_cap")
    if policy in ("jev", "zoom"):
        lane["api_attempts"] += 1
        lane["journal"].emit(
            "request",
            decision_index=lane["decisions"] + 1,
            body=payload_for(
                policy,
                canonical,
                lane["ranker"].model,
                getattr(lane["ranker"], "zoom_question", "choice"),
                getattr(lane["ranker"], "zoom_model", "zoom-decisions"),
            ),
        )
    display.update(lane, "Waiting for API" if policy in ("jev", "zoom") else "Ranking")
    ranking = lane["ranker"].choose(canonical, remaining, cancelled=display.refresh)
    if display.cancelled:
        raise BudgetStop("cancelled")
    if time.monotonic() >= lane["deadline"]:
        raise BudgetStop("wall_time_cap")
    return ranking


def summary(lane, attempt):
    sim = lane["sim"]
    return {
        "policy": lane["policy"],
        "attempt": attempt,
        "seed": sim.seed,
        "reason": lane["reason"] or "running",
        "best_x": sim.best_x,
        "reward": sim.reward,
        "game_frames": sim.frames,
        "decisions": lane["decisions"],
        "api_attempts": lane["api_attempts"],
        "latencies_ms": list(lane["latencies"]),
        "simulation_frames": lane["budget"].used,
        "wall_seconds": lane["wall_used"]
        + (time.monotonic() - lane["active_start"] if lane["active_start"] is not None else 0),
        "error": lane.get("error"),
        "cost_usd": None,
        "diagnostics": dict(lane["diagnostics"]),
        "survival_guard": lane.get("survival_guard", False),
    }


def episode_run(args, capture=False):
    survival_guard = getattr(args, "survival_guard", False)
    if survival_guard and capture:
        raise ValueError("--survival-guard is supported only for assisted episodes")
    config = SimulationConfig(args.horizon, args.landing_cap, args.settle, args.depth)
    policies = (
        ["search"]
        if capture
        else (
            ["fixture-jev", "fixture-zoom", "search"] if args.offline else ["jev", "zoom", "search"]
        )
    )
    # Fail before creating episodes or making paid requests when a required key is absent.
    rankers = {name: Ranker(name, args.timeout, args.model) for name in policies}
    for ranker in rankers.values():
        ranker.zoom_question = getattr(args, "zoom_question", "choice")
        ranker.zoom_model = getattr(args, "zoom_model", "zoom-decisions")
    track = "corpus_capture" if capture else "episodes"
    root = new_run(
        args.artifacts_dir,
        {
            "track": track,
            "mode": "assisted",
            "offline": args.offline or capture,
            "env": args.env,
            "seed": args.seed,
            "episodes": args.episodes,
            "simulation": asdict(config),
            "model_requested": args.model,
            "zoom_model_requested": getattr(args, "zoom_model", "zoom-decisions"),
            "zoom_question": getattr(args, "zoom_question", "choice"),
            "limits": {
                key: getattr(args, key)
                for key in (
                    "max_decisions",
                    "game_frames",
                    "simulation_frames",
                    "wall_seconds",
                    "stall_frames",
                    "timeout",
                )
            },
            "scheduling": "independent parallel lanes",
            "automatic_escape": False,
            "automatic_followup": False,
            "survival_guard": survival_guard,
        },
    )
    print(f"Artifacts: {root.resolve()}", flush=True)
    all_rows, corpus = [], []
    display = Display(not args.headless and not capture, args.offline)
    try:
        for attempt in range(1, args.episodes + 1):
            lanes = []
            try:
                for policy in policies:
                    sim = MarioSimulator(args.env, args.seed + attempt - 1)
                    started = time.monotonic()
                    journal = Journal(root / f"{policy}-{attempt:03d}.jsonl")
                    lane = {
                        "policy": policy,
                        "survival_guard": survival_guard,
                        "ranker": rankers[policy],
                        "sim": sim,
                        "journal": journal,
                        "started": started,
                        "deadline": started + args.wall_seconds,
                        "reason": None,
                        "wall_used": 0.0,
                        "active_start": None,
                        "diagnostics": Counter(),
                        "decisions": 0,
                        "api_attempts": 0,
                        "latencies": [],
                        "prefix": [],
                        "last_gain": 0,
                        "last_best": sim.best_x,
                        "display": {
                            "name": {
                                "jev": "TypeSafe Jev",
                                "zoom": "Zoom Decisions",
                                "fixture-jev": "Jev [OFFLINE FIXTURE]",
                                "fixture-zoom": "Zoom [OFFLINE FIXTURE]",
                                "search": "Search baseline",
                            }[policy],
                            "method": (
                                "Assisted + survival guard · " if survival_guard else "Assisted · "
                            )
                            + (
                                "native Choice"
                                if policy == "jev"
                                else (
                                    "native Choice"
                                    if getattr(args, "zoom_question", "choice") == "choice"
                                    else "independent predicates"
                                )
                                if policy == "zoom"
                                else "deterministic search"
                            ),
                            "frame": sim.frame,
                            "status": "Ready",
                            "action": None,
                            "best_x": sim.best_x,
                            "reward": 0.0,
                            "latency": 0.0,
                        },
                    }
                    lane["budget"] = WorkBudget(
                        args.simulation_frames, lane["deadline"], cancelled=display.refresh
                    )
                    lanes.append(lane)
                    journal.emit(
                        "start",
                        policy=policy,
                        env=args.env,
                        seed=sim.seed,
                        initial_digest=sim.digest(),
                        simulation=asdict(config),
                        provenance=provenance(),
                    )
                display.rows = [lane["display"] for lane in lanes]
                display.context = f"Assisted parallel · {args.env} · Seed {args.seed + attempt - 1}"
                if display.view:
                    display.view.subtitle = f"{display.context} · Independent lanes · Q to stop"
                for lane in lanes:
                    lane["summary"] = summary(lane, attempt)

                def run_lane(lane, attempt=attempt):
                    sim, journal = lane["sim"], lane["journal"]
                    while lane["reason"] is None:
                        lane["active_start"] = time.monotonic()
                        lane["deadline"] = (
                            lane["active_start"] + args.wall_seconds - lane["wall_used"]
                        )
                        lane["budget"].deadline = lane["deadline"]
                        try:
                            if display.cancelled:
                                raise BudgetStop("cancelled")
                            if lane["decisions"] >= args.max_decisions:
                                raise BudgetStop("decision_cap")
                            display.update(lane, "Simulating outcomes")
                            before = sim.digest()
                            outcomes = sim.explore(config, lane["budget"])
                            canonical = canonical_state(sim, outcomes, config)
                            journal.emit(
                                "evidence",
                                decision_index=lane["decisions"] + 1,
                                digest=before,
                                canonical=canonical,
                            )
                            if capture:
                                corpus.append(
                                    {
                                        "id": f"{attempt}-{lane['decisions'] + 1}",
                                        "seed": sim.seed,
                                        "prefix": list(lane["prefix"]),
                                        "decision_history": copy.deepcopy(sim.recent_decisions),
                                        "digest": before,
                                        "canonical": canonical,
                                        "tags": scenario_tags(canonical),
                                    }
                                )
                            ranking = choose_with_events(lane, canonical, display)
                            lane["decisions"] += 1
                            if lane["policy"] in ("jev", "zoom"):
                                lane["latencies"].append(ranking.latency_ms)
                            lane["display"].update(
                                action=ranking.candidate, latency=ranking.latency_ms
                            )
                            diagnostics = selection_diagnostics(canonical, ranking.candidate)
                            lane["diagnostics"].update(
                                {key: int(value) for key, value in diagnostics.items()}
                            )
                            journal.emit(
                                "ranking",
                                decision_index=lane["decisions"],
                                diagnostics=diagnostics,
                                **asdict(ranking),
                            )
                            # Preserve the provider ranking verbatim. Only execution changes.
                            candidate = ranking.candidate
                            intervention = None
                            if survival_guard:
                                intervention = survival_selection(
                                    canonical, candidate, ranking.scores
                                )
                                candidate = intervention["applied_candidate"]
                                lane["diagnostics"]["survival_guard_overrides"] += int(
                                    intervention["overridden"]
                                )
                                journal.emit(
                                    "survival_guard",
                                    decision_index=lane["decisions"],
                                    **intervention,
                                )
                                lane["display"]["action"] = candidate
                            applied = []
                            execution_start = sim.digest()
                            decision_start = sim.state()
                            execution_complete = False
                            airborne_case = []

                            def guard(lane=lane, sim=sim):
                                if display.refresh():
                                    raise BudgetStop("cancelled")
                                if time.monotonic() >= lane["deadline"]:
                                    raise BudgetStop("wall_time_cap")
                                if sim.frames >= args.game_frames:
                                    raise BudgetStop("game_frame_cap")
                                if sim.frames - lane["last_gain"] >= args.stall_frames:
                                    raise BudgetStop("stalled")

                            playback = FramePacer() if display.view else None

                            def on_frame(
                                lane=lane,
                                sim=sim,
                                applied=applied,
                                airborne_case=airborne_case,
                                playback=playback,
                            ):
                                applied.append(sim.last_action)
                                if (
                                    capture
                                    and not sim.grounded
                                    and not sim.done
                                    and not airborne_case
                                    and not any("airborne" in case["tags"] for case in corpus)
                                ):
                                    airborne_case.append(
                                        (sim.checkpoint(), lane["prefix"] + applied)
                                    )
                                if sim.best_x > lane["last_best"]:
                                    lane["last_gain"], lane["last_best"] = (
                                        sim.frames,
                                        sim.best_x,
                                    )
                                display.update(lane, "Executing")
                                if playback:
                                    playback.tick()

                            try:
                                result = sim.execute(
                                    candidate,
                                    config,
                                    before_step=guard,
                                    on_frame=on_frame,
                                )
                                execution_complete = True
                                if result["digest_after"] != outcomes[candidate]["digest_after"]:
                                    raise RuntimeError(
                                        "Actual execution diverged from its simulated candidate"
                                    )
                            finally:
                                lane["prefix"].extend(applied)
                                sim.record_decision(candidate, decision_start, execution_complete)
                                journal.emit(
                                    "execution",
                                    source="survival_guard"
                                    if intervention and intervention["overridden"]
                                    else "policy",
                                    candidate=candidate,
                                    decision_index=lane["decisions"],
                                    before_digest=execution_start,
                                    after_digest=sim.digest(),
                                    state_after=sim.state(),
                                    actions=applied,
                                    complete=execution_complete,
                                )
                            if airborne_case:
                                end_state = sim.checkpoint()
                                try:
                                    checkpoint, prefix = airborne_case[0]
                                    sim.restore(checkpoint)
                                    mid_outcomes = sim.explore(config, lane["budget"])
                                    mid_canonical = canonical_state(sim, mid_outcomes, config)
                                    corpus.append(
                                        {
                                            "id": f"{attempt}-{lane['decisions']}-airborne",
                                            "seed": sim.seed,
                                            "prefix": prefix,
                                            "decision_history": copy.deepcopy(sim.recent_decisions),
                                            "digest": sim.digest(),
                                            "canonical": mid_canonical,
                                            "tags": scenario_tags(mid_canonical),
                                        }
                                    )
                                finally:
                                    sim.restore(end_state)
                            if sim.done:
                                lane["reason"] = (
                                    "completed"
                                    if sim.clear
                                    else "died"
                                    if sim.dead
                                    else "truncated"
                                    if sim.truncated
                                    else "terminated"
                                )
                        except BudgetStop as exc:
                            lane["reason"] = str(exc)
                        except ProviderError as exc:
                            lane["reason"] = (
                                "cancelled" if exc.category == "cancelled" else "provider_error"
                            )
                            lane["error"] = {"category": exc.category, "detail": str(exc)}
                            journal.emit(
                                "provider_error",
                                decision_index=lane["decisions"] + 1,
                                **lane["error"],
                            )
                        except Exception as exc:  # noqa: BLE001 — persist partial evidence, then fail the run
                            lane["reason"] = "harness_error"
                            lane["error"] = {
                                "category": type(exc).__name__,
                                "detail": "Harness failed; check snapshot compatibility and event evidence",
                            }
                            journal.emit("harness_error", **lane["error"])
                        lane["wall_used"] += time.monotonic() - lane["active_start"]
                        lane["active_start"] = None
                        if lane["reason"]:
                            display.update(lane, lane["reason"].replace("_", " ").capitalize())
                        lane["summary"] = summary(lane, attempt)

                last_report = 0.0

                def refresh(lanes=lanes):
                    nonlocal last_report
                    display.refresh()
                    if time.monotonic() - last_report < 0.25:
                        return
                    last_report = time.monotonic()
                    report(
                        root,
                        all_rows + [lane["summary"] for lane in lanes],
                        track,
                        args.offline or capture,
                    )

                run_workers(
                    [lambda lane=lane: run_lane(lane) for lane in lanes],
                    refresh,
                    lambda: setattr(display, "cancelled", True),
                )
            except KeyboardInterrupt:
                display.cancelled = True
            finally:
                for lane in lanes:
                    lane["reason"] = lane["reason"] or "cancelled"
                    row = summary(lane, attempt)
                    lane["journal"].emit("end", summary=row, final_digest=lane["sim"].digest())
                    all_rows.append(row)
                    lane["journal"].close()
                    lane["sim"].close()
                report(root, all_rows, track, args.offline or capture)
            if display.cancelled:
                break
        if capture:
            required = {"open", "enemy", "obstacle", "gap", "airborne"}
            tags = {tag for case in corpus for tag in case["tags"]}
            write_json(
                root / "corpus.json",
                {
                    **provenance(),
                    "env": args.env,
                    "simulation": asdict(config),
                    "cases": corpus,
                    "coverage": sorted(tags),
                    "missing_coverage": sorted(required - tags),
                    "note": "Deterministic search trajectory; finite-horizon evidence, not an exhaustive benchmark.",
                },
            )
        display.finish(args)
    finally:
        display.close()
    print(f"Report: {(root / 'report.md').resolve()}")
    return 1 if any(row["error"] for row in all_rows) else 130 if display.cancelled else 0


def scenario_tags(canonical):
    outcomes = canonical["outcomes"]
    tags = ["grounded" if canonical["state"]["grounded"] else "airborne"]
    # Semantic scene tags are recorded from the upstream per-state geometry below.
    tags.extend(canonical.get("scene_tags", []))
    if all(o["status"] == "alive" for o in outcomes.values()):
        tags.append("all_candidates_survive_horizon")
    return sorted(set(tags))


def compatible(saved):
    current = provenance()
    if saved.get("schema") != SCHEMA or saved.get("action_set") != ACTION_SET:
        raise ValueError(
            "Unsupported artifact schema/action set; direct-control logs are not assisted logs"
        )
    if saved.get("dependencies") != current["dependencies"]:
        raise ValueError(
            "Dependency versions differ from the recorded artifact; restore its locked environment"
        )


def load_events(path):
    records = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records or records[0].get("event") != "start":
        raise ValueError("Expected a versioned assisted episode log with a start event")
    compatible(records[0]["provenance"])
    return records


def replay(path):
    records = load_events(path)
    start = records[0]
    sim = MarioSimulator(start["env"], start["seed"])
    count = 0
    try:
        if sim.digest() != start["initial_digest"]:
            raise ValueError("Replay diverged at the initial state")
        for event in records[1:]:
            if event["event"] == "execution":
                if sim.digest() != event["before_digest"]:
                    raise ValueError("Replay diverged before a recorded action sequence")
                for action in event["actions"]:
                    sim.step(action)
                    count += 1
                if sim.digest() != event["after_digest"]:
                    raise ValueError("Replay diverged after a recorded action sequence")
            elif event["event"] == "end" and sim.digest() != event["final_digest"]:
                raise ValueError("Replay final state diverged")
        print(
            f"Replay verified: {count} actual frames; zero API calls"
            + ("; partial log" if records[-1]["event"] != "end" else "")
        )
        return 0
    finally:
        sim.close()


def reconstruct_prefix(sim, case, config, budget):
    """Recompute retained decision history from actual prefix controls, not claims."""
    prefix = case["prefix"]
    for decision in case.get("decision_history", []):
        start = decision["before"]["game_frames"]
        end = decision["after"]["game_frames"]
        if not decision["complete"] or not sim.frames <= start < end <= len(prefix):
            raise ValueError("Invalid corpus decision boundaries")
        while sim.frames < start:
            budget.step()
            sim.step(prefix[sim.frames])
        before = sim.state()
        if before != decision["before"]:
            raise ValueError("Corpus decision start does not reproduce")
        actual = sim.execute(decision["candidate"], config, before_step=budget.step)
        if sim.frames != end or actual["actions"] != prefix[start:end]:
            raise ValueError("Corpus decision controls do not reproduce")
        sim.record_decision(decision["candidate"], before, True)
        if sim.recent_decisions[-1] != decision:
            raise ValueError("Corpus decision outcome does not reproduce")
    while sim.frames < len(prefix):
        budget.step()
        sim.step(prefix[sim.frames])


def evaluate_corpus(args):
    source = args.corpus.read_bytes()
    corpus = json.loads(source)
    compatible(corpus)
    if corpus.get("evidence_version") != EVIDENCE_VERSION:
        raise ValueError(
            "Corpus lacks current progress/cycle evidence; recapture it. Old episode logs still replay."
        )
    if corpus.get("simulation", {}).get("continuation_set") not in (
        "all-seven-v1",
        "all-seven-airborne-v2",
    ):
        raise ValueError(
            "Corpus predates all-seven continuation/history evidence; recapture it. Old episode logs can still be replayed."
        )
    if not corpus.get("cases"):
        raise ValueError("Corpus contains no decision states")
    policies = (
        ["fixture-jev", "fixture-zoom", "search"] if args.offline else ["jev", "zoom", "search"]
    )
    rankers = {name: Ranker(name, args.timeout, args.model) for name in policies}
    for ranker in rankers.values():
        ranker.zoom_question = getattr(args, "zoom_question", "choice")
        ranker.zoom_model = getattr(args, "zoom_model", "zoom-decisions")
    root = new_run(
        args.artifacts_dir,
        {
            "track": "identical_states",
            "offline": args.offline,
            "corpus_sha256": hashlib.sha256(source).hexdigest(),
            "corpus_source": str(args.corpus),
            "simulation": corpus["simulation"],
            "env": corpus["env"],
            "seeds": sorted({case["seed"] for case in corpus["cases"]}),
            "model_requested": args.model,
            "zoom_model_requested": getattr(args, "zoom_model", "zoom-decisions"),
            "zoom_question": getattr(args, "zoom_question", "choice"),
            "limits": {
                key: getattr(args, key)
                for key in (
                    "max_decisions",
                    "game_frames",
                    "simulation_frames",
                    "wall_seconds",
                    "timeout",
                )
            },
            "budget_scope": "wall and simulation limits span the evaluation; game_frames caps each replay prefix",
        },
    )
    # Retain the exact bytes so the saved corpus hash can be checked independently.
    (root / "corpus.json").write_bytes(source)
    rows, decisions = [], []
    shared = {"simulation_frames": 0, "wall_seconds": 0.0}
    report(root, rows, "identical_states", args.offline, shared)
    print(f"Artifacts: {root.resolve()}", flush=True)
    deadline = time.monotonic() + args.wall_seconds
    budget = WorkBudget(args.simulation_frames, deadline)
    with (root / "rankings.jsonl").open("w", encoding="utf-8") as log:

        def emit(event):
            log.write(json.dumps({"schema": SCHEMA, **event}) + "\n")
            log.flush()

        for case in corpus["cases"][: args.max_decisions]:
            validation_started = time.monotonic()
            validation_frames = budget.used
            sim = None
            try:
                if len(case["prefix"]) > args.game_frames:
                    raise BudgetStop("checkpoint_replay_frame_cap")
                sim = MarioSimulator(corpus["env"], case["seed"])
                config = SimulationConfig(**corpus["simulation"])
                reconstruct_prefix(sim, case, config, budget)
                if sim.digest() != case["digest"]:
                    raise ValueError(
                        "Corpus checkpoint diverged; do not score stale or altered evidence"
                    )
                outcomes = sim.explore(config, budget)
                canonical = canonical_state(sim, outcomes, config)
                if canonical != case["canonical"]:
                    raise ValueError("Corpus outcomes do not reproduce on this simulator")
            except (ValueError, BudgetStop, KeyboardInterrupt) as exc:
                shared["simulation_frames"] = budget.used
                shared["wall_seconds"] += time.monotonic() - validation_started
                reason = (
                    str(exc)
                    if isinstance(exc, BudgetStop)
                    else "cancelled"
                    if isinstance(exc, KeyboardInterrupt)
                    else "corpus_validation_failed"
                )
                failure = {
                    "category": reason if isinstance(exc, BudgetStop) else type(exc).__name__,
                    "detail": "Checkpoint validation stopped; inspect corpus and configured budgets",
                }
                emit({"event": reason, "case_id": case["id"], "error": failure})
                rows.append(
                    {
                        "policy": "corpus-validation",
                        "attempt": case["id"],
                        "reason": reason,
                        "best_x": sim.best_x if sim else 0,
                        "game_frames": sim.frames if sim else 0,
                        "decisions": 0,
                        "api_attempts": 0,
                        "latencies_ms": [],
                        "simulation_frames": 0,
                        "wall_seconds": 0.0,
                        "error": failure,
                    }
                )
                report(root, rows, "identical_states", args.offline, shared)
                raise
            finally:
                if sim:
                    sim.close()
            shared["simulation_frames"] = budget.used
            shared["wall_seconds"] += time.monotonic() - validation_started
            emit(
                {
                    "event": "case_validated",
                    "case_id": case["id"],
                    "shared_simulation_frames": budget.used - validation_frames,
                    "shared_wall_seconds": time.monotonic() - validation_started,
                }
            )
            for policy in policies:
                started = time.monotonic()
                row = {
                    "policy": policy,
                    "attempt": case["id"],
                    "best_x": canonical["state"]["x"],
                    "game_frames": 0,
                    "simulation_frames": 0,
                    "decisions": 0,
                    "latencies_ms": [],
                    "api_attempts": 0,
                    "error": None,
                }
                event = {
                    "event": "ranking",
                    "case_id": case["id"],
                    "policy": policy,
                    "canonical": copy.deepcopy(canonical),
                }
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BudgetStop("wall_time_cap")
                    if policy in ("jev", "zoom"):
                        request_body = payload_for(
                            policy,
                            canonical,
                            args.model,
                            getattr(args, "zoom_question", "choice"),
                            getattr(args, "zoom_model", "zoom-decisions"),
                        )
                        emit(
                            {
                                "event": "request",
                                "case_id": case["id"],
                                "policy": policy,
                                "body": request_body,
                            }
                        )
                        event["request"] = request_body
                        row["api_attempts"] = 1
                    ranking = rankers[policy].choose(canonical, min(args.timeout, remaining))
                    event.update(asdict(ranking))
                    selected = canonical["outcomes"][ranking.candidate]
                    event["fatal_when_survivor_available"] = selected["status"] == "dead" and any(
                        v["status"] in ("alive", "clear") for v in canonical["outcomes"].values()
                    )
                    event["selected_dx"] = selected["dx"]
                    diagnostics = selection_diagnostics(canonical, ranking.candidate)
                    event["diagnostics"] = diagnostics
                    row["diagnostics"] = {key: int(value) for key, value in diagnostics.items()}
                    row.update(reason="ranked", decisions=1)
                    if policy in ("jev", "zoom"):
                        row["latencies_ms"] = [ranking.latency_ms]
                except (ProviderError, BudgetStop, KeyboardInterrupt) as exc:
                    category = (
                        exc.category
                        if isinstance(exc, ProviderError)
                        else "cancelled"
                        if isinstance(exc, KeyboardInterrupt)
                        else str(exc)
                    )
                    row.update(
                        reason="provider_error" if isinstance(exc, ProviderError) else category,
                        error={
                            "category": category,
                            "detail": str(exc)
                            if isinstance(exc, ProviderError)
                            else "Evaluation budget exhausted or cancelled",
                        },
                    )
                    event["error"] = row["error"]
                row["wall_seconds"] = time.monotonic() - started
                emit(event)
                rows.append(row)
                decisions.append(event)
                report(root, rows, "identical_states", args.offline, shared)
                if row["reason"] in ("cancelled", "wall_time_cap"):
                    return 130 if row["reason"] == "cancelled" else 1
    comparisons = []
    for case in corpus["cases"][: args.max_decisions]:
        results = [r for r in decisions if r["case_id"] == case["id"]]
        comparisons.append(
            {
                "case_id": case["id"],
                "choices": {r["policy"]: r.get("candidate") for r in results},
                "all_agree": len(results) == 3
                and all("candidate" in r for r in results)
                and len({r["candidate"] for r in results}) == 1,
            }
        )
    write_json(root / "agreement.json", comparisons)
    with (root / "report.md").open("a", encoding="utf-8") as report_file:
        report_file.write("\n## Identical-state diagnostics\n\n")
        report_file.write(
            f"Shared reconstruction/simulation work: {budget.used} frames (not charged three times).\n\n"
        )
        for policy in policies:
            valid = [d for d in decisions if d["policy"] == policy and "candidate" in d]
            fatal = sum(d["fatal_when_survivor_available"] for d in valid)
            report_file.write(
                f"- {policy}: {len(valid)} successful rankings; {fatal} chose a known fatal option with a surviving alternative.\n"
            )
        report_file.write(
            f"\nAll three policies agreed on {sum(c['all_agree'] for c in comparisons)}/{len(comparisons)} cases (errors do not count as agreement).\n"
        )
    print(f"Report: {(root / 'report.md').resolve()}")
    return 1 if any(row["error"] for row in rows) else 0


def positive(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main(argv):
    parser = argparse.ArgumentParser(description="Assisted Mario outcome-ranking evaluation")
    parser.add_argument(
        "command", choices=("assisted", "realtime", "capture", "evaluate", "replay")
    )
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument(
        "--offline", action="store_true", help="Deterministic fixtures, not model results"
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--exit-when-done", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--env", default="SuperMarioBros-1-1-v0")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--episodes", type=positive, default=3)
    parser.add_argument("--max-decisions", type=positive, default=25)
    parser.add_argument("--game-frames", type=positive, default=3600)
    parser.add_argument("--simulation-frames", type=positive, default=200000)
    parser.add_argument("--wall-seconds", type=positive, default=180)
    parser.add_argument("--stall-frames", type=positive, default=360)
    parser.add_argument("--timeout", type=positive, default=30)
    parser.add_argument("--horizon", type=positive, default=48)
    parser.add_argument("--landing-cap", type=int, default=72)
    parser.add_argument("--settle", type=int, default=4)
    parser.add_argument("--depth", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument(
        "--model",
        default="jev-latest",
        help="Jev model selector only; use --zoom-model for Zoom",
    )
    parser.add_argument(
        "--survival-guard",
        action="store_true",
        help="Assisted episodes only: log and replace predicted fatal choices when a surviving alternative exists",
    )
    parser.add_argument(
        "--zoom-question",
        choices=("choice", "predicate"),
        default="choice",
        help="Zoom assisted/realtime/evaluate question type (default: native choice)",
    )
    parser.add_argument(
        "--zoom-model",
        choices=("zoom-decisions", "zoom-decisions-pro"),
        default="zoom-decisions",
        help="Zoom model to compare against Jev",
    )
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    if args.survival_guard and args.command != "assisted":
        parser.error(
            "--survival-guard requires assisted; it cannot protect stale real-time predictions"
        )
    if args.screenshot and (args.headless or args.command not in ("assisted", "realtime")):
        parser.error(
            "--screenshot needs an assisted or realtime desktop display (SDL dummy display is supported)"
        )
    if args.command in ("replay", "evaluate") and not args.file:
        parser.error("This command requires an artifact file path")
    try:
        if args.command == "realtime":
            from .realtime import run

            return run(args)
        if args.command == "replay":
            return replay(args.file)
        if args.command == "evaluate":
            args.corpus = args.file
            return evaluate_corpus(args)
        return episode_run(args, capture=args.command == "capture")
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
