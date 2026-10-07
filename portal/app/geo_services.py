"""Shared per-installation upstream throttling, including multiple worker processes."""
import fcntl
import time
from contextlib import contextmanager
from pathlib import Path
from .config import settings


@contextmanager
def paced(service):
    directory = Path(settings.data_dir) / 'service-limits'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (service + '.lock')).open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            try:
                previous = float(handle.read() or 0)
            except ValueError:
                previous = 0
            delay = min(1.05, max(0, 1.05 - (time.time() - previous)))
            if delay:
                time.sleep(delay)
            yield
        finally:
            handle.seek(0)
            handle.truncate()
            handle.write(str(time.time()))
            handle.flush()
            fcntl.flock(handle, fcntl.LOCK_UN)
