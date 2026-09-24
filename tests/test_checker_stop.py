import asyncio
import time
import unittest
from unittest.mock import patch

from core import checker
from core.models import CheckConfig


class _Page:
    closed = 0

    async def goto(self, *_a, **_kw):
        await asyncio.sleep(60)  # a page that never finishes loading

    async def close(self):
        _Page.closed += 1


class _Context:
    async def new_page(self):
        return _Page()

    async def close(self):
        pass


class _Browser:
    async def new_context(self, **_kw):
        return _Context()

    async def close(self):
        pass


class _Chromium:
    async def launch(self, **_kw):
        return _Browser()


class _PW:
    chromium = _Chromium()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class RunCheckStopTest(unittest.TestCase):
    def test_stop_cancels_in_flight_pages(self):
        _Page.closed = 0
        results: list = []

        async def main() -> float:
            stop = asyncio.Event()
            cfg = CheckConfig(
                task_id=1,
                donor_urls=[(i, f"https://d.example/{i}") for i in range(5)],
                target_domains=["t.example"],
                threads=3,
                timeout=60,
            )
            task = asyncio.create_task(
                checker.run_check(cfg, results.append, lambda *_: None, stop)
            )
            await asyncio.sleep(0.2)
            started = time.monotonic()
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            return time.monotonic() - started

        with patch.object(checker, "async_playwright", _PW):
            elapsed = asyncio.run(main())

        self.assertLess(elapsed, 2.0)
        # Cancelled donors stay pending — no result is reported for them.
        self.assertEqual(results, [])
        # Pages in flight are still closed on the way out.
        self.assertEqual(_Page.closed, 3)


if __name__ == "__main__":
    unittest.main()
