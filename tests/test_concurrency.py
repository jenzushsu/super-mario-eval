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
