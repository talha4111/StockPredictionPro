"""QuantBot'un ayni calisma dizininde tek surec olarak calismasini saglar."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import IO


class InstanceAlreadyRunning(RuntimeError):
    """Ayni bot icin baska bir ana surec kilidi tuttugunda firlatilir."""


def _lock_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(__file__).resolve().with_name("quantbot.pid")


def acquire_instance_lock(
    path: str | os.PathLike[str] | None = None,
) -> IO[str]:
    """Non-blocking process lock alir ve kilit dosyasina PID yazar."""

    lock_path = _lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="ascii")

    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == "":
                handle.write("0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as exc:
        handle.close()
        raise InstanceAlreadyRunning(
            f"QuantBot zaten calisiyor; kilit alinamadi: {lock_path}"
        ) from exc

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except OSError:
        pass

    def _release() -> None:
        if handle.closed:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()

    atexit.register(_release)
    return handle
