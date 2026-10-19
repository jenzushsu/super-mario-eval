from threading import Event, get_ident

import pytest

from mario_eval.assisted import Display
from mario_eval.concurrency import run_workers


def test_ui_stays_on_caller_and_cancellation_joins_workers():
    caller = get_ident()
    stop = Event()
    entered = [Event(), Event()]
    finished = [Event(), Event()]

    def job(index):
        assert get_ident() != caller
        entered[index].set()
        assert stop.wait(5)
        finished[index].set()

    def refresh():
        assert get_ident() == caller
        if all(event.is_set() for event in entered):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_workers([lambda i=i: job(i) for i in range(2)], refresh, stop.set)
    assert all(event.is_set() for event in finished)


def test_worker_display_refresh_only_observes_cancellation():
    display = Display(False, True)

    class MainThreadView:
        def draw(self, *args):
            pytest.fail("Worker called desktop rendering")

    display.view = MainThreadView()
    display.rows = [{}, {}]
    display.cancelled = True
    run_workers([lambda: display.refresh(force=True)], lambda: None, lambda: None)


def test_pacing_subtracts_work_and_does_not_burst_after_slow_frames():
    from mario_eval.concurrency import FramePacer

    now = [0.0]
    waits = []

    def wait(seconds):
        waits.append(seconds)
        now[0] += seconds

    pacer = FramePacer(clock=lambda: now[0], wait=wait)
    now[0] += 0.005  # Emulator/render work consumes part of a frame.
    pacer.tick()
    assert waits[-1] == pytest.approx(1 / 60 - 0.005)
    assert now[0] == pytest.approx(1 / 60)
    now[0] += 1  # A long interruption must not cause a sequence of fast frames.
    pacer.tick()
    assert len(waits) == 1
    pacer.tick()
    assert waits[-1] == pytest.approx(1 / 60)


def test_assisted_display_draws_each_scheduler_frame(monkeypatch):
    display = Display(False, True)
    draws = []

    class View:
        def draw(self, rows, status):
            draws.append(status)
            return True

    display.view = View()
    display.rows = [{}, {}]
    # These refreshes represent scheduler ticks at 60 Hz. The former 50 ms
    # throttle skipped most of them, even when the renderer could keep up.
    now = [10.0]
    monkeypatch.setattr("mario_eval.assisted.time.monotonic", lambda: now[0])
    for _ in range(60):
        display.refresh()
        now[0] += 1 / 60
    assert len(draws) == 60
