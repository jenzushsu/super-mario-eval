"""Independent lane workers with UI/event handling on the calling thread."""

import time
from concurrent.futures import ThreadPoolExecutor


def run_workers(jobs, refresh, cancel):
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="mario-lane") as pool:
        futures = [pool.submit(job) for job in jobs]
        try:
            while not all(future.done() for future in futures):
                for future in futures:
                    if future.done():
                        future.result()
                refresh()
                time.sleep(0.016)
        except BaseException:
            cancel()
            raise
        finally:
            # Workers observe cancellation before cleanup closes their emulators/logs.
            if any(future.done() and future.exception() for future in futures):
                cancel()
        for future in futures:
            future.result()
