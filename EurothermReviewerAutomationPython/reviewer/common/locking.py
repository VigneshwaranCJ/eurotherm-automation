"""Exclusive run locks with conservative interrupted-run behavior."""
from contextlib import contextmanager
import os


@contextmanager
def run_lock(filename):
    try:
        handle = filename.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise RuntimeError("Another run or interrupted-run lock exists. Verify no run is active before removing automation.lock.") from error
    try:
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        handle.close()
        filename.unlink()
