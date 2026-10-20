"""Latency-sensitive evaluation: live emulators never wait for their planners."""

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from .assisted import Display, summary
from .concurrency import FramePacer, run_workers
from .rankers import ProviderError, Ranker, payload_for
from .reporting import Journal, new_run, provenance, report
from .simulation import (
    BudgetStop,
    MarioSimulator,
    SimulationConfig,
    WorkBudget,
    canonical_state,
    selection_diagnostics,
)


class HeldMove:
    """Hold direction between replies; a fresh jump releases once then holds 8/32 frames."""

    def __init__(self, candidate="wait"):
        self.candidate = candidate
        self.age = 0

    def next(self, grounded):
        name = self.candidate
        jump = name in ("jump", "run_jump", "hop")
        button = {
            "run": "right_run",
            "walk": "right",
            "jump": "right_jump",
            "run_jump": "right_run_jump",
            "hop": "right_jump",
            "wait": "noop",
            "back": "left",
        }[name]
        if jump and self.age == 0 and grounded:
            button = "noop"
        elif jump and self.age >= (8 if name == "hop" else 32):
            button = "right_run" if name == "run_jump" else "right"
        self.age += 1
        return button


def run(args):
    config = SimulationConfig(args.horizon, args.landing_cap, args.settle, args.depth)
    policies = (
        ["fixture-jev", "fixture-zoom", "search"] if args.offline else ["jev", "zoom", "search"]
    )
    rankers = {
        name: Ranker(
            name,
            args.timeout,
            args.model,
            args.zoom_question,
            getattr(args, "zoom_model", "zoom-decisions"),
        )
        for name in policies
    }
    root = new_run(
        args.artifacts_dir,
        {
            "track": "realtime",
            "mode": "realtime-assisted",
            "offline": args.offline,
            "env": args.env,
            "seed": args.seed,
            "episodes": args.episodes,
            "simulation": asdict(config),
            "zoom_question": args.zoom_question,
            "model_requested": args.model,
            "zoom_model_requested": getattr(args, "zoom_model", "zoom-decisions"),
            "scheduling": "independent live and planning workers",
            "controller": "held-move-v1",
            "bootstrap": "neutral until first reply; emulator keeps running",
            "stale_response_policy": "apply on arrival if episode still running; log age",
            "target_fps": 60,
            "automatic_escape": False,
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
        },
    )
    print(f"Artifacts: {root.resolve()}", flush=True)
    display = Display(not args.headless, args.offline)
    all_rows = []
    try:
        for attempt in range(1, args.episodes + 1):
            lanes = []
            try:
                for name in policies:
                    sim = MarioSimulator(args.env, args.seed + attempt - 1)
                    stop = threading.Event()
                    lane = {
                        "policy": name,
                        "sim": sim,
                        "reason": None,
                        "decisions": 0,
                        "api_attempts": 0,
                        "latencies": [],
                        "diagnostics": Counter(),
                        "wall_used": 0.0,
                        "active_start": None,
                        "ages": [],
                        "stop": stop,
                        "journal": Journal(root / f"{name}-{attempt:03d}.jsonl"),
                        "display": {
                            "name": name + (" [OFFLINE]" if args.offline else ""),
                            "method": "Real-time · decisions applied on arrival",
                            "frame": sim.frame,
                            "status": "Starting",
                            "action": "wait",
                            "best_x": sim.best_x,
                            "reward": 0.0,
                            "latency": 0.0,
                        },
                    }
                    lane["budget"] = WorkBudget(
                        args.simulation_frames,
                        float("inf"),
                        cancelled=lambda stop=stop: stop.is_set() or display.cancelled,
                    )
                    lanes.append(lane)
                    lane["journal"].emit(
                        "start",
                        policy=name,
                        env=args.env,
                        seed=sim.seed,
                        initial_digest=sim.digest(),
                        simulation=asdict(config),
                        track="realtime",
                        controller="held-move-v1",
                        provenance=provenance(),
                    )
                    lane["summary"] = summary(lane, attempt)
                display.rows = [lane["display"] for lane in lanes]
                display.context = f"Real-time · {args.env} · Seed {args.seed + attempt - 1}"
                if display.view:
                    display.view.subtitle = (
                        f"{display.context} · Game continues during inference · Q to stop"
                    )

                def run_lane(lane, attempt=attempt):
                    sim, journal, stop = lane["sim"], lane["journal"], lane["stop"]
                    lane["active_start"] = time.monotonic()
                    deadline = lane["active_start"] + args.wall_seconds
                    lane["budget"].deadline = deadline
                    move = HeldMove()
                    applied = []
                    before_digest = sim.digest()
                    pending = None
                    requests = 0
                    pacer = FramePacer(
                        wait=stop.wait
                    )  # Also paced headlessly: latency is part of the experiment.

                    def flush():
                        nonlocal before_digest
                        if applied:
                            journal.emit(
                                "execution",
                                source="held_move" if lane["decisions"] else "bootstrap",
                                candidate=move.candidate,
                                decision_index=lane["decisions"],
                                before_digest=before_digest,
                                after_digest=sim.digest(),
                                state_after=sim.state(),
                                actions=list(applied),
                                complete=True,
                            )
                            applied.clear()
                            before_digest = sim.digest()

                    def plan(checkpoint, index, observed_frame):
                        # This emulator belongs exclusively to the planner, never the live loop.
                        planning = MarioSimulator(args.env, sim.seed)
                        try:
                            planning.restore(checkpoint)
                            outcomes = planning.explore(config, lane["budget"])
                            canonical = canonical_state(planning, outcomes, config)
                            journal.emit(
                                "evidence",
                                decision_index=index,
                                observed_frame=observed_frame,
                                digest=planning.digest(),
                                canonical=canonical,
                            )
                            if lane["budget"].cancelled():
                                raise BudgetStop("cancelled")
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise BudgetStop("wall_time_cap")
                            ranker = rankers[lane["policy"]]
                            if lane["policy"] in ("jev", "zoom"):
                                lane["api_attempts"] += 1
                                journal.emit(
                                    "request",
                                    decision_index=index,
                                    observed_frame=observed_frame,
                                    body=payload_for(
                                        lane["policy"],
                                        canonical,
                                        args.model,
                                        args.zoom_question,
                                        getattr(args, "zoom_model", "zoom-decisions"),
                                    ),
                                )
                            ranking = ranker.choose(
                                canonical, remaining, cancelled=lane["budget"].cancelled
                            )
                            return ranking, canonical, observed_frame
                        finally:
                            planning.close()

                    try:
                        with ThreadPoolExecutor(
                            max_workers=1, thread_name_prefix="mario-planner"
                        ) as pool:
                            try:
                                while True:
                                    if display.cancelled:
                                        raise BudgetStop("cancelled")
                                    if time.monotonic() >= deadline:
                                        raise BudgetStop("wall_time_cap")
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
                                        break
                                    if sim.frames >= args.game_frames:
                                        raise BudgetStop("game_frame_cap")
                                    if sim.frames - sim.last_gain_frame >= args.stall_frames:
                                        raise BudgetStop("stalled")
                                    if pending is not None and pending.done():
                                        ranking, canonical, observed = pending.result()
                                        pending = None
                                        flush()
                                        lane["decisions"] += 1
                                        age = sim.frames - observed
                                        lane["ages"].append(age)
                                        diagnostics = selection_diagnostics(
                                            canonical, ranking.candidate
                                        )
                                        lane["diagnostics"].update(
                                            {key: int(value) for key, value in diagnostics.items()}
                                        )
                                        if lane["policy"] in ("jev", "zoom"):
                                            lane["latencies"].append(ranking.latency_ms)
                                        journal.emit(
                                            "ranking",
                                            decision_index=lane["decisions"],
                                            observed_frame=observed,
                                            applied_frame=sim.frames,
                                            decision_age_frames=age,
                                            diagnostics=diagnostics,
                                            **asdict(ranking),
                                        )
                                        move = HeldMove(ranking.candidate)
                                        lane["display"].update(
                                            action=ranking.candidate, latency=ranking.latency_ms
                                        )
                                    if pending is None and requests < args.max_decisions:
                                        requests += 1
                                        pending = pool.submit(
                                            plan, sim.checkpoint(), requests, sim.frames
                                        )
                                    if (
                                        lane["decisions"] >= args.max_decisions
                                        and move.age >= config.horizon
                                    ):
                                        raise BudgetStop("decision_cap")
                                    action = move.next(sim.grounded)
                                    sim.step(action)
                                    applied.append(action)
                                    if len(applied) >= 30:
                                        flush()
                                    display.update(
                                        lane,
                                        "Playing · next decision pending" if pending else "Playing",
                                    )
                                    lane["summary"] = summary(lane, attempt) | {
                                        "decision_age_frames": list(lane["ages"])
                                    }
                                    pacer.tick()
                            finally:
                                stop.set()
                                flush()
                    except BudgetStop as exc:
                        lane["reason"] = str(exc)
                    except ProviderError as exc:
                        lane["reason"] = (
                            "cancelled" if exc.category == "cancelled" else "provider_error"
                        )
                        lane["error"] = {"category": exc.category, "detail": str(exc)}
                        journal.emit("provider_error", **lane["error"])
                    except Exception as exc:  # noqa: BLE001 — retain partial run evidence
                        lane["reason"] = "harness_error"
                        lane["error"] = {
                            "category": type(exc).__name__,
                            "detail": "Real-time worker failed",
                        }
                        journal.emit("harness_error", **lane["error"])
                    finally:
                        if pending is not None:
                            discarded = {}
                            try:
                                ranking, _, observed = pending.result()
                                discarded = {
                                    "observed_frame": observed,
                                    "response": asdict(ranking),
                                }
                            except (ProviderError, BudgetStop) as exc:
                                discarded = {
                                    "category": exc.category
                                    if isinstance(exc, ProviderError)
                                    else str(exc)
                                }
                            except Exception as exc:  # noqa: BLE001 — preserve safe failure category
                                discarded = {"category": type(exc).__name__}
                            journal.emit(
                                "discarded_decision",
                                decision_index=requests,
                                reason="Episode stopped; outstanding response not applied",
                                **discarded,
                            )
                        lane["wall_used"] = time.monotonic() - lane["active_start"]
                        lane["active_start"] = None
                        display.update(
                            lane, (lane["reason"] or "stopped").replace("_", " ").capitalize()
                        )
                        lane["summary"] = summary(lane, attempt) | {
                            "decision_age_frames": list(lane["ages"])
                        }

                last_report = 0.0

                def refresh(lanes=lanes):
                    nonlocal last_report
                    display.refresh()
                    if time.monotonic() - last_report >= 0.25:
                        report(
                            root,
                            all_rows + [lane["summary"] for lane in lanes],
                            "realtime",
                            args.offline,
                        )
                        last_report = time.monotonic()

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
                    row = summary(lane, attempt) | {"decision_age_frames": list(lane["ages"])}
                    lane["journal"].emit("end", summary=row, final_digest=lane["sim"].digest())
                    all_rows.append(row)
                    lane["journal"].close()
                    lane["sim"].close()
                report(root, all_rows, "realtime", args.offline)
            if display.cancelled:
                break
        display.finish(args)
    finally:
        display.close()
    print(f"Report: {(root / 'report.md').resolve()}")
    return 130 if display.cancelled else 1 if any(row.get("error") for row in all_rows) else 0
