"""Publish complete local files without truncating the previous version."""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_output(path):
    target = Path(path)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp{target.suffix}")
    try:
        yield temporary
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path, text, *, encoding="utf-8"):
    with atomic_output(path) as temporary:
        temporary.write_text(text, encoding=encoding, newline='')


@contextmanager
def atomic_open(path, *args, **kwargs):
    with atomic_output(path) as temporary:
        with temporary.open(*args, **kwargs) as handle:
            yield handle
