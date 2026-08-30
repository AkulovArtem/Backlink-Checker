import unittest

from gui.worker import loop_accepts_stop


class _Loop:
    def __init__(self, running: bool):
        self._running = running

    def is_running(self) -> bool:
        return self._running


class LoopAcceptsStopTest(unittest.TestCase):
    def test_none(self):
        self.assertFalse(loop_accepts_stop(None))

    def test_not_running(self):
        self.assertFalse(loop_accepts_stop(_Loop(False)))

    def test_running(self):
        self.assertTrue(loop_accepts_stop(_Loop(True)))


if __name__ == "__main__":
    unittest.main()
