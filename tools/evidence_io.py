"""Read saved evidence files only; never open block devices or FIFOs."""
from contextlib import contextmanager
import os
import stat


@contextmanager
def regular_file(path):
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise ValueError('expected a saved regular file, not a device or stream')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('input changed to a non-regular file')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            yield stream
    finally:
        if fd is not None:
            os.close(fd)
