"""Independent lane workers with UI/event handling on the calling thread."""

import time
from concurrent.futures import ThreadPoolExecutor


class FramePacer:
    """Target a display cadence without accumulating work time or catch-up bursts."""

    def __init__(self, fps=60, clock=time.monotonic, wait=time.sleep):
        self.interval = 1 / fps
        self.clock = clock
        self.wait = wait
        self.deadline = clock()

    def tick(self):
        self.deadline += self.interval
        remaining = self.deadline - self.clock()
        if remaining > 0:
            self.wait(remaining)
        else:
            # Slow frames drop the timing debt, not emulator frames.
            self.deadline = self.clock()


def run_workers(jobs, refresh, cancel):
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="mario-lane") as pool:
        futures = [pool.submit(job) for job in jobs]
        pacer = FramePacer()
        try:
            while not all(future.done() for future in futures):
                for future in futures:
                    if future.done():
                        future.result()
                refresh()
                pacer.tick()
        except BaseException:
            cancel()
            raise
        finally:
            # Workers observe cancellation before cleanup closes their emulators/logs.
            if any(future.done() and future.exception() for future in futures):
                cancel()
        for future in futures:
            future.result()
