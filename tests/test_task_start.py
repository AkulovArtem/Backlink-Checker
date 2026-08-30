import unittest

from core.task_start import (
    bump_generation,
    can_launch_after_balance,
    is_current_generation,
    is_task_busy,
    take_finished_worker,
)


class GenerationTest(unittest.TestCase):
    def test_stale_generation_after_bump(self):
        store: dict[int, int] = {}
        first = bump_generation(store, 7)
        self.assertTrue(is_current_generation(store, 7, first))
        second = bump_generation(store, 7)
        self.assertFalse(is_current_generation(store, 7, first))
        self.assertTrue(is_current_generation(store, 7, second))

    def test_cancel_then_new_start_ignores_old_slot(self):
        store: dict[int, int] = {}
        old = bump_generation(store, 1)
        bump_generation(store, 1)  # cancel
        new = bump_generation(store, 1)  # retry
        self.assertFalse(is_current_generation(store, 1, old))
        self.assertTrue(is_current_generation(store, 1, new))


class CanLaunchTest(unittest.TestCase):
    def test_happy_path(self):
        self.assertTrue(
            can_launch_after_balance(
                closing=False,
                gen_current=True,
                task_exists=True,
                has_worker=False,
            )
        )

    def test_deleted_during_dialog(self):
        self.assertFalse(
            can_launch_after_balance(
                closing=False,
                gen_current=True,
                task_exists=False,
                has_worker=False,
            )
        )

    def test_closing(self):
        self.assertFalse(
            can_launch_after_balance(
                closing=True,
                gen_current=True,
                task_exists=True,
                has_worker=False,
            )
        )

    def test_stale_thread(self):
        self.assertFalse(
            can_launch_after_balance(
                closing=False,
                gen_current=False,
                task_exists=True,
                has_worker=False,
            )
        )

    def test_already_has_worker(self):
        self.assertFalse(
            can_launch_after_balance(
                closing=False,
                gen_current=True,
                task_exists=True,
                has_worker=True,
            )
        )


class IsTaskBusyTest(unittest.TestCase):
    def test_idle(self):
        self.assertFalse(
            is_task_busy(
                closing=False,
                has_worker=False,
                is_starting=False,
                is_stopping=False,
            )
        )

    def test_stopping_blocks_new_start(self):
        self.assertTrue(
            is_task_busy(
                closing=False,
                has_worker=False,
                is_starting=False,
                is_stopping=True,
            )
        )

    def test_closing_blocks_new_start(self):
        self.assertTrue(
            is_task_busy(
                closing=True,
                has_worker=False,
                is_starting=False,
                is_stopping=False,
            )
        )


class TakeFinishedWorkerTest(unittest.TestCase):
    def test_stale_finish_leaves_new_worker(self):
        old, new = object(), object()
        workers = {7: new}
        self.assertFalse(take_finished_worker(workers, 7, old))
        self.assertIs(workers[7], new)

    def test_matching_worker_is_removed(self):
        worker = object()
        workers = {7: worker}
        self.assertTrue(take_finished_worker(workers, 7, worker))
        self.assertNotIn(7, workers)

    def test_none_worker_does_not_pop(self):
        worker = object()
        workers = {7: worker}
        self.assertFalse(take_finished_worker(workers, 7, None))
        self.assertIs(workers[7], worker)


if __name__ == "__main__":
    unittest.main()
