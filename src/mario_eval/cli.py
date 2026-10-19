from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from typesafe_mario.actions import ACTION_TO_INDEX, JUMP_RELEASE_ACTION, Action
from typesafe_mario.policy import HeuristicPolicy, TypeSafePolicy
from typesafe_mario.runner import _unwrap_ram, create_mario_env
from typesafe_mario.state import MarioStateParser

from .zoom import ZoomAPIError, ZoomPolicy


class View:
    def __init__(self, subtitle):
        import pygame

        self.pg = pygame
        pygame.init()
        self.screen = pygame.display.set_mode((1120, 760))
        pygame.display.set_caption("Mario • Jev / Zoom Decisions")
        self.title = pygame.font.SysFont("DejaVu Sans", 26, bold=True)
        self.body = pygame.font.SysFont("DejaVu Sans", 17)
        self.small = pygame.font.SysFont("DejaVu Sans", 14)
        self.subtitle = subtitle

    def draw(self, lanes, status):
        pg = self.pg
        self.screen.fill((15, 17, 21))

        def text(value, x, y, font=None, color=(236, 239, 243)):
            self.screen.blit((font or self.body).render(value, True, color), (x, y))

        text("Mario / Decision comparison", 32, 22, self.title)
        text(self.subtitle, 32, 62, self.small, (172, 182, 196))
        for index, lane in enumerate(lanes):
            x = 32 + index * 552
            text(lane["name"], x, 105, self.title)
            text(lane["method"], x, 143, self.small, (172, 182, 196))
            surface = pg.surfarray.make_surface(lane["frame"].swapaxes(0, 1))
            self.screen.blit(pg.transform.scale(surface, (512, 480)), (x, 177))
            text(f"{lane['status']}  ·  {lane['action'] or 'No action yet'}", x, 674)
            text(
                f"Best x {lane['best_x']}   Reward {lane['reward']:.0f}   "
                f"API {lane['latency']:.0f} ms",
                x,
                708,
                self.small,
            )
        pg.display.flip()
        for event in pg.event.get():
            if event.type == pg.QUIT or (
                event.type == pg.KEYDOWN and event.key in (pg.K_ESCAPE, pg.K_q)
            ):
                return False
        return True

    def close(self):
        self.pg.quit()


def controller_action(action, snapshot, frame_index):
    # Match the upstream dashboard: a grounded jump needs a button-up edge.
    if frame_index == 0 and snapshot.grounded and action in JUMP_RELEASE_ACTION:
        return JUMP_RELEASE_ACTION[action]
    return action


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def run(args):
    if not args.offline:
        missing = [
            name for name in ("TYPESAFE_API_KEY", "ZOOM_API_KEY") if not os.environ.get(name)
        ]
        if missing:
            raise RuntimeError(
                "Configure these keys in environment settings: " + ", ".join(missing)
            )
    policies = (
        [HeuristicPolicy(), HeuristicPolicy()] if args.offline else [TypeSafePolicy(), ZoomPolicy()]
    )
    run_dir = args.artifacts_dir / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8])
    run_dir.mkdir(parents=True)
    config = {
        "env": args.env,
        "seed": args.seed,
        "frames_per_decision": args.frames_per_decision,
        "max_decisions": args.max_decisions,
        "offline": args.offline,
        "mode": "paired lockstep; emulator paused during inference",
        "upstream_commit": "ca22449ed187118d19326d1f54b01b6636578aa4",
    }
    (run_dir / "config.json").write_text(json.dumps(config, indent=2))
    lanes, view = [], None
    cancelled = False
    try:
        for index, policy in enumerate(policies):
            env = create_mario_env(args.env, render_mode="rgb_array")
            lane = {
                "env": env,
                "policy": policy,
                "parser": MarioStateParser(decision_horizon_frames=args.frames_per_decision),
                "name": ("TypeSafe Jev", "Zoom Decisions")[index],
                "method": (
                    "Native choice + jump / danger",
                    "Independent predicates → highest score",
                )[index],
                "status": "Ready",
                "action": None,
                "reward": 0.0,
                "last_reward": 0.0,
                "latency": 0.0,
                "latencies": [],
                "best_x": 0,
                "count": 0,
                "done": False,
                "clear": False,
                "dead": False,
                "log": (run_dir / ("jev.jsonl", "zoom.jsonl")[index]).open("w"),
            }
            lanes.append(lane)
            lane["frame"], lane["info"] = env.reset(seed=args.seed)
            lane["snapshot"] = lane["parser"].parse(lane["info"], _unwrap_ram(env))
            lane["best_x"] = int(lane["info"].get("x_pos", 0))
            lane["frames"] = 0
            if args.offline:
                lane["name"] += " [OFFLINE]"
                lane["method"] = "Heuristic smoke test · no model calls"
        if not args.headless:
            view = View(
                f"{args.env} · Seed {args.seed} · {args.frames_per_decision} frames/action · Paused inference · Q to exit"
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            for _ in range(args.max_decisions):
                pending = []
                for lane in lanes:
                    if lane["done"]:
                        continue
                    snapshot = lane["snapshot"]
                    lane["status"] = "Choosing"
                    pending.append(
                        (
                            lane,
                            snapshot,
                            pool.submit(lane["policy"].choose, snapshot, tuple(Action)),
                        )
                    )
                if not pending:
                    break
                while not all(future.done() for _, _, future in pending):
                    if view and not view.draw(lanes, "Choosing"):
                        cancelled = True
                        break
                    time.sleep(0.016)
                if cancelled:
                    break
                for lane, snapshot, future in pending:
                    try:
                        decision = future.result()
                    except Exception as exc:  # noqa: BLE001 — isolate provider failures without hiding the failed run
                        lane["status"] = "API error; see summary"
                        lane["error"] = {
                            "category": type(exc).__name__,
                            "decision_index": lane["count"] + 1,
                            "detail": str(exc)
                            if isinstance(exc, ZoomAPIError)
                            else "Provider call failed; check credentials, connectivity and response schema.",
                        }
                        lane["log"].write(
                            json.dumps({"event": "provider_error", **lane["error"]}) + "\n"
                        )
                        lane["log"].flush()
                        lane["done"] = True
                        continue
                    lane["action"] = decision.action.value
                    lane["latency"] = decision.latency_ms
                    lane["latencies"].append(decision.latency_ms)
                    lane["last_reward"] = 0.0
                    lane["decision"] = decision
                    lane["executed_actions"] = []
                    lane["status"] = "Running"
                # Render each emulator frame; neither provider gains simulated time during inference.
                for _frame in range(args.frames_per_decision):
                    for lane, _, _ in pending:
                        if lane["done"]:
                            continue
                        applied = controller_action(
                            Action(lane["action"]), lane["snapshot"], _frame
                        )
                        frame, reward, terminated, truncated, info = lane["env"].step(
                            ACTION_TO_INDEX[applied]
                        )
                        lane["executed_actions"].append(applied.value)
                        lane["frames"] += 1
                        lane["snapshot"] = lane["parser"].parse(
                            info,
                            _unwrap_ram(lane["env"]),
                            previous_action=applied.value,
                            previous_reward=float(reward),
                            previous_latency_ms=lane["latency"],
                            previous_response_delay_frames=0,
                        )
                        lane.update(frame=frame, info=info)
                        lane["last_reward"] += float(reward)
                        lane["reward"] += float(reward)
                        lane["best_x"] = max(lane["best_x"], int(info.get("x_pos", 0)))
                        lane["clear"] = bool(info.get("clear", False))
                        lane["dead"] = bool(info.get("death", False))
                        lane["done"] = terminated or truncated or lane["clear"] or lane["dead"]
                        if lane["done"]:
                            lane["status"] = (
                                "Cleared"
                                if lane["clear"]
                                else "Died"
                                if lane["dead"]
                                else "Truncated"
                                if truncated
                                else "Episode ended"
                            )
                    if view:
                        if not view.draw(lanes, "Running"):
                            cancelled = True
                            break
                        time.sleep(1 / 60)
                for lane, snapshot, _ in pending:
                    if "error" in lane:
                        continue
                    lane["count"] += 1
                    record = {
                        "decision_index": lane["count"],
                        "state": snapshot.to_state(),
                        "state_after": lane["snapshot"].to_state(),
                        "executed_actions": lane["executed_actions"],
                        "emulator_frames": lane["frames"],
                        "decision": asdict(lane["decision"]),
                        "reward": lane["last_reward"],
                        "total_reward": lane["reward"],
                        "best_x": lane["best_x"],
                        "clear": lane["clear"],
                        "dead": lane["dead"],
                        "done": lane["done"],
                        "metadata": getattr(lane["policy"], "last_metadata", {}),
                        "score_semantics": "independent predicates"
                        if lane is lanes[1] and not args.offline
                        else "choice",
                    }
                    lane["log"].write(json.dumps(record) + "\n")
                    lane["log"].flush()
                if cancelled:
                    break
        for lane in lanes:
            if not lane["done"]:
                lane["status"] = "Stopped" if cancelled else "Decision limit reached"
        if view:
            view.draw(lanes, "Finished")
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                view.pg.image.save(view.screen, str(args.screenshot))
        summary = [
            {
                key: lane[key]
                for key in ("name", "status", "count", "best_x", "reward", "clear", "dead")
            }
            | {
                "emulator_frames": lane["frames"],
                "simulated_seconds": lane["frames"] / 60,
                "mean_latency_ms": statistics.mean(lane["latencies"])
                if lane["latencies"]
                else None,
                "error": lane.get("error"),
            }
            for lane in lanes
        ]
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        print(f"Artifacts: {run_dir.resolve()}")
        if view and not args.exit_when_done and not cancelled:
            while view.draw(lanes, "Finished"):
                time.sleep(0.05)
        return 1 if any("error" in lane for lane in lanes) else 0
    finally:
        for lane in lanes:
            lane["log"].close()
            lane["env"].close()
        for policy in policies:
            if hasattr(policy, "close"):
                policy.close()
        if view:
            view.close()


def main():
    parser = argparse.ArgumentParser(description="Compare Jev and Zoom in paired Mario episodes")
    parser.add_argument("--env", default="SuperMarioBros-1-1-v0")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument(
        "--frames-per-decision",
        type=positive,
        choices=[8],
        default=8,
        help="Fixed at 8 to match the upstream Jev prompt",
    )
    parser.add_argument("--max-decisions", type=positive, default=250)
    parser.add_argument(
        "--offline", action="store_true", help="Use two explicitly labeled heuristic controllers"
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--exit-when-done", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    if args.headless and args.screenshot:
        parser.error(
            "--screenshot requires the display; use SDL_VIDEODRIVER=dummy on a cloud machine"
        )
    try:
        return run(args)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
