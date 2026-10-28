import multiprocessing
import tempfile
import unittest
from pathlib import Path

from instance_lock import InstanceAlreadyRunning, acquire_instance_lock


def _try_lock(path, queue):
    try:
        handle = acquire_instance_lock(path)
    except InstanceAlreadyRunning:
        queue.put("blocked")
        return
    queue.put("acquired")
    handle.close()


class InstanceLockTests(unittest.TestCase):
    def test_second_process_cannot_acquire_same_lock(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path = Path(tmp) / "quantbot.pid"
            first = acquire_instance_lock(path)
            try:
                queue = multiprocessing.Queue()
                process = multiprocessing.Process(
                    target=_try_lock,
                    args=(str(path), queue),
                )
                process.start()
                process.join(timeout=5)
                self.assertEqual(process.exitcode, 0)
                self.assertEqual(queue.get(timeout=1), "blocked")
            finally:
                first.close()

    def test_lock_can_be_reacquired_after_release(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path = Path(tmp) / "quantbot.pid"
            first = acquire_instance_lock(path)
            first.close()
            second = acquire_instance_lock(path)
            second.close()
