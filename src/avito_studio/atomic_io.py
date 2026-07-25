"""Crash-safe local file writes.

Every write is completed in a temporary file in the destination directory,
flushed to disk, and then installed with :func:`os.replace`.  The destination
therefore always contains either the previous complete value or the new
complete value; a truncated YAML/JSON file is never exposed to the application.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

TextWriter = Callable[[TextIO], Any]


def atomic_write(path: str | Path, writer: TextWriter) -> None:
    """Atomically replace *path* with text produced by *writer*.

    The temporary file deliberately lives next to the destination: ``replace``
    is only guaranteed to be atomic within one filesystem.  On any exception
    the old destination remains untouched and the temporary file is removed.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            descriptor_open = False
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if descriptor_open:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: str | Path, text: str) -> None:
    """Atomically write UTF-8 *text* using stable LF newlines."""
    atomic_write(path, lambda stream: stream.write(text))


def atomic_write_json(
    path: str | Path,
    value: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
) -> None:
    """Atomically write a JSON document terminated by one newline."""
    text = json.dumps(value, ensure_ascii=ensure_ascii, indent=indent) + "\n"
    atomic_write_text(path, text)


def atomic_write_yaml(path: str | Path, value: Any, yaml: Any) -> None:
    """Atomically dump *value* with a configured ruamel ``YAML`` instance."""
    atomic_write(path, lambda stream: yaml.dump(value, stream))


def _fsync_directory(directory: Path) -> None:
    """Persist a directory entry where the platform supports directory fsync."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
