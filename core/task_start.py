"""Start-generation helpers so stale balance threads cannot launch a worker."""


def bump_generation(store: dict[int, int], task_id: int) -> int:
    store[task_id] = store.get(task_id, 0) + 1
    return store[task_id]


def is_current_generation(store: dict[int, int], task_id: int, gen: int) -> bool:
    return store.get(task_id) == gen


def can_launch_after_balance(
    *,
    closing: bool,
    gen_current: bool,
    task_exists: bool,
    has_worker: bool,
) -> bool:
    return (not closing) and gen_current and task_exists and not has_worker


def is_task_busy(
    *,
    closing: bool,
    has_worker: bool,
    is_starting: bool,
    is_stopping: bool,
) -> bool:
    """True if start/retry must not launch another worker for this task."""
    return closing or has_worker or is_starting or is_stopping


def take_finished_worker(workers: dict, task_id: int, worker) -> bool:
    """Pop ``task_id`` only if ``worker`` is still the active one.

    A queued ``finished`` from a stopped thread must not drop a worker that
    was started after the old one reaped.
    """
    if worker is None or workers.get(task_id) is not worker:
        return False
    workers.pop(task_id, None)
    return True
